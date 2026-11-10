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
    consulta_id_ignorar: Optional[int] = None
) -> datetime:
    """
    Aplica todas as regras de negócio para um agendamento:
    1. Antecedência mínima de 2 dias (a partir das 08:00 do 2º dia).
    2. Dias úteis (segunda a sexta).
    3. Horário comercial (08:00 às 18:00).
    4. Horário fechado/redondo (minuto 00).
    5. Anti-choque com outras consultas ativas da psicóloga.

    Retorna o data_hora_fim calculado caso tudo esteja válido.
    """
    fuso_psicologa = ZoneInfo(psicologa.time_zone)

    # Converte o horário solicitado para o fuso local da psicóloga para checar as regras do consultório dela
    inicio_local = data_hora_inicio_solicitada.astimezone(fuso_psicologa)

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
    # REGRA 2: Antecedência mínima de 2 dias (a partir das 08:00 do segundo dia)
    # Ex: Segunda-feira -> primeiro horário permitido é Quarta-feira às 08:00.
    # --------------------------------------------------------------------------
    agora = datetime.now(fuso_psicologa)
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
                f"Agendamentos exigem no mínimo 2 dias de antecedência. "
                f"O próximo horário disponível mais cedo é {horario_minimo_permitido.strftime('%d/%m/%Y às %H:%M (%Z)')}."
            )
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
    # --------------------------------------------------------------------------
    query_conflito = db.query(Consultas).filter(
        Consultas.psicologa_id == psicologa.id,
        Consultas.status != Status.CANCELADA,  # Consultas canceladas não bloqueiam a agenda!
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
            detail="A psicóloga já possui uma consulta agendada neste horário. Por favor, escolha outro horário."
        )

    return data_hora_fim


def obter_horarios_disponiveis(
    db: Session,
    psicologa: User,
    dia_desejado: date
) -> list[datetime]:
    """
    Dado um dia específico, calcula todos os slots comerciais possíveis (08:00 às 17:00)
    e retorna apenas aqueles que estão livres na agenda da psicóloga e atendem à antecedência mínima.
    """
    fuso_psicologa = ZoneInfo(psicologa.time_zone)
    agora = datetime.now(fuso_psicologa)

    # 1. Se for sábado ou domingo, nenhum horário está disponível
    if dia_desejado.weekday() >= 5:
        return []

    # 2. Regra de antecedência mínima de 2 dias (a partir das 08:00)
    data_minima_permitida = agora.date() + timedelta(days=2)
    horario_minimo_permitido = datetime.combine(
        data_minima_permitida,
        time(hour=HORA_INICIO_ATENDIMENTO),
        tzinfo=fuso_psicologa
    )

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
            Consultas.status != Status.CANCELADA,
            Consultas.data_hora_inicio < slot_fim,
            Consultas.data_hora_fim > slot_inicio
        ).first()

        if not conflito:
            horarios_livres.append(slot_inicio)

    return horarios_livres

