from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from database.consultas import Consultas, Status
from database.usermodel import User


# ==============================================================================
# CONFIGURAÇÕES DA AGENDA
# ==============================================================================
DURACAO_CONSULTA_MINUTOS = 50
HORA_INICIO_ATENDIMENTO = 8   # 08:00
HORA_FIM_ATENDIMENTO = 18     # 18:00 (última consulta pode iniciar às 17:00 e terminar às 17:50)


def validar_regras_agendamento(
    db: Session,
    psicologa: User,
    data_hora_inicio_solicitada: datetime,
    consulta_id_ignorar: Optional[int] = None,
    exigir_antecedencia: bool = True
) -> datetime:
    """
    Aplica as regras de negócio para um agendamento:
    1. Antecedência mínima de 2 dias (a partir das 08:00 do 2º dia) - APLICADA APENAS AO PACIENTE.
       Se for a psicóloga agendando (exigir_antecedencia=False), apenas valida se não é no passado.
    2. Minuto e segundo zerados (slots redondos para garantir 10 min de descanso entre sessões).
    3. Dias úteis (segunda a sexta).
    4. Horário comercial (08:00 às 18:00).
    5. Anti-choque com outras consultas confirmadas/pendentes da psicóloga.

    Retorna o data_hora_fim calculado caso tudo esteja válido.
    """
    fuso_psicologa = ZoneInfo(psicologa.time_zone)

    # Converte o horário solicitado para o fuso local da psicóloga para checar as regras do consultório dela
    inicio_local = data_hora_inicio_solicitada.astimezone(fuso_psicologa)
    agora = datetime.now(fuso_psicologa)

    # --------------------------------------------------------------------------
    # REGRA 1: Minuto e segundo zerados (Slots redondos)
    # Garante consultas às 08:00, 09:00 e os 10 minutos de intervalo automático!
    # --------------------------------------------------------------------------
    if inicio_local.minute != 0 or inicio_local.second != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="As consultas devem iniciar no início da hora cheia (ex: 08:00, 09:00, 14:00...)."
        )

    # --------------------------------------------------------------------------
    # REGRA 2: Antecedência mínima
    # Paciente: 2 dias de antecedência (a partir das 08:00 do segundo dia útil/corrido).
    # Psicóloga: sem antecedência mínima, apenas não pode agendar no passado.
    # --------------------------------------------------------------------------
    if exigir_antecedencia:
        data_minima_permitida = agora.date() + timedelta(days=2)
        horario_minimo_permitido = datetime.combine(
            data_minima_permitida,
            time(hour=HORA_INICIO_ATENDIMENTO),
            tzinfo=fuso_psicologa
        )

        if inicio_local < horario_minimo_permitido:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Agendamentos de pacientes exigem no mínimo 2 dias de antecedência. "
                    f"O próximo horário disponível mais cedo é {horario_minimo_permitido.strftime('%d/%m/%Y às %H:%M (%Z)')}."
                )
            )
    else:
        if inicio_local < agora:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível agendar uma consulta em uma data/horário que já passou."
            )

    # --------------------------------------------------------------------------
    # REGRA 3: Apenas dias úteis (Segunda a Sexta)
    # No Python: 0=Segunda, 1=Terça, ..., 4=Sexta, 5=Sábado, 6=Domingo
    # --------------------------------------------------------------------------
    if inicio_local.weekday() >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A psicóloga realiza atendimentos apenas de segunda a sexta-feira."
        )

    # --------------------------------------------------------------------------
    # REGRA 4: Horário comercial (08:00 às 18:00)
    # --------------------------------------------------------------------------
    if inicio_local.hour < HORA_INICIO_ATENDIMENTO or inicio_local.hour >= HORA_FIM_ATENDIMENTO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Atendimentos permitidos apenas entre {HORA_INICIO_ATENDIMENTO:02d}:00 e {HORA_FIM_ATENDIMENTO:02d}:00."
        )

    # --------------------------------------------------------------------------
    # REGRA 5: Duração da sessão e cálculo do término
    # --------------------------------------------------------------------------
    data_hora_fim = data_hora_inicio_solicitada + timedelta(minutes=DURACAO_CONSULTA_MINUTOS)

    # --------------------------------------------------------------------------
    # REGRA 6: Anti-Choque (Colisão de Horários na Agenda)
    # Não colide com consultas CANCELADAS ou RECUSADAS!
    # --------------------------------------------------------------------------
    query_conflito = db.query(Consultas).filter(
        Consultas.psicologa_id == psicologa.id,
        Consultas.status.notin_([Status.CANCELADA, Status.RECUSADA]),
        Consultas.data_hora_inicio < data_hora_fim,
        Consultas.data_hora_fim > data_hora_inicio_solicitada
    )

    # Se estiver reagendando, ignora a própria consulta atual
    if consulta_id_ignorar:
        query_conflito = query_conflito.filter(Consultas.id != consulta_id_ignorar)

    conflito = query_conflito.first()
    if conflito:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A psicóloga já possui uma consulta agendada ou pendente neste horário. Por favor, escolha outro horário."
        )

    return data_hora_fim


def obter_horarios_disponiveis(
    db: Session,
    psicologa: User,
    dia_desejado: date,
    exigir_antecedencia: bool = True
) -> list[datetime]:
    """
    Dado um dia específico, calcula todos os slots comerciais possíveis (08:00 às 17:00)
    e retorna apenas aqueles que estão livres na agenda da psicóloga.
    """
    fuso_psicologa = ZoneInfo(psicologa.time_zone)
    agora = datetime.now(fuso_psicologa)

    # 1. Se for sábado ou domingo, nenhum horário está disponível
    if dia_desejado.weekday() >= 5:
        return []

    # 2. Regra de antecedência mínima de 2 dias (a partir das 08:00) se for paciente
    if exigir_antecedencia:
        data_minima_permitida = agora.date() + timedelta(days=2)
        horario_minimo_permitido = datetime.combine(
            data_minima_permitida,
            time(hour=HORA_INICIO_ATENDIMENTO),
            tzinfo=fuso_psicologa
        )
    else:
        horario_minimo_permitido = agora

    horarios_livres = []

    # 3. Itera por cada hora de atendimento: 08h, 09h, 10h, ..., 17h
    for hora in range(HORA_INICIO_ATENDIMENTO, HORA_FIM_ATENDIMENTO):
        slot_inicio = datetime.combine(
            dia_desejado,
            time(hour=hora, minute=0, second=0),
            tzinfo=fuso_psicologa
        )
        slot_fim = slot_inicio + timedelta(minutes=DURACAO_CONSULTA_MINUTOS)

        # Se o slot estiver antes da antecedência mínima permitida, pula
        if slot_inicio < horario_minimo_permitido:
            continue

        # Verifica se já existe consulta ativa colidindo com este slot
        conflito = db.query(Consultas).filter(
            Consultas.psicologa_id == psicologa.id,
            Consultas.status.notin_([Status.CANCELADA, Status.RECUSADA]),
            Consultas.data_hora_inicio < slot_fim,
            Consultas.data_hora_fim > slot_inicio
        ).first()

        if not conflito:
            horarios_livres.append(slot_inicio)

    return horarios_livres


def gerar_consultas_recorrentes(
    db: Session,
    psicologa: User,
    paciente: User,
    quantidade_semanas: int = 8
) -> list[Consultas]:
    """
    Gera as consultas futuras fixas para o paciente com base em:
    - paciente.dia_semana_fixo (0=Segunda, ..., 4=Sexta)
    - paciente.horario_fixo (ex: '16:00')
    - paciente.tipo_recorrencia (SEMANAL ou QUINZENAL)

    Cria as consultas já com status CONFIRMADA (pois foram definidas pela psicóloga).
    """
    from database.usermodel import RecorrenciaTipo

    if paciente.dia_semana_fixo is None or not paciente.horario_fixo:
        return []

    fuso_psicologa = ZoneInfo(psicologa.time_zone)
    hora_str, min_str = paciente.horario_fixo.split(":")
    hora_fixa = int(hora_str)
    minuto_fixo = int(min_str)

    agora = datetime.now(fuso_psicologa)
    # Encontra o próximo dia da semana correspondente
    dias_a_frente = (paciente.dia_semana_fixo - agora.weekday()) % 7
    if dias_a_frente == 0 and agora.hour >= hora_fixa:
        dias_a_frente = 7  # Se for hoje mas o horário já passou, vai para a próxima semana

    primeira_data = agora.date() + timedelta(days=dias_a_frente)

    intervalo_dias = 7 if paciente.tipo_recorrencia == RecorrenciaTipo.SEMANAL else 14
    total_sessoes = quantidade_semanas if paciente.tipo_recorrencia == RecorrenciaTipo.SEMANAL else (quantidade_semanas // 2)

    novas_consultas = []
    for i in range(total_sessoes):
        data_sessao = primeira_data + timedelta(days=i * intervalo_dias)
        inicio_sessao = datetime.combine(
            data_sessao,
            time(hour=hora_fixa, minute=minuto_fixo),
            tzinfo=fuso_psicologa
        )
        fim_sessao = inicio_sessao + timedelta(minutes=DURACAO_CONSULTA_MINUTOS)

        # Checa se já existe consulta nesse horário para esse paciente ou outro
        existente = db.query(Consultas).filter(
            Consultas.psicologa_id == psicologa.id,
            Consultas.status.notin_([Status.CANCELADA, Status.RECUSADA]),
            Consultas.data_hora_inicio < fim_sessao,
            Consultas.data_hora_fim > inicio_sessao
        ).first()

        if not existente:
            consulta = Consultas(
                psicologa_id=psicologa.id,
                paciente_id=paciente.id,
                data_hora_inicio=inicio_sessao,
                data_hora_fim=fim_sessao,
                status=Status.CONFIRMADA,
                lembrete_enviado=False
            )
            db.add(consulta)
            novas_consultas.append(consulta)

    db.commit()
    for c in novas_consultas:
        db.refresh(c)
    return novas_consultas


