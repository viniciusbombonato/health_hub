"""
Script de teste prático para validar nossa modelagem e a conversão de Timezone.
Execute com: uv run python test_db.py
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from health_hub.database import Base, SessionLocal, engine
from health_hub.models import Consulta, Disponibilidade, StatusConsulta, TipoUsuario, Usuario


def main():
    print("1. Criando as tabelas no SQLite local...")
    Base.metadata.create_all(bind=engine)
    print(" Tabelas criadas com sucesso!\n")

    # Abrindo uma sessão com o banco de dados
    with SessionLocal() as db:
        print("2. Inserindo a Psicóloga e um Paciente internacional...")

        # Cadastrando a psicóloga (em São Paulo)
        psicologa = Usuario(
            nome_completo="Carolina Silva (Psicóloga)",
            email="carolina@exemplo.com",
            telefone="+5511988887777",
            tipo=TipoUsuario.PSICOLOGA,
            fuso_horario="America/Sao_Paulo",
        )

        # Cadastrando um paciente que mora em Lisboa (Portugal)
        paciente = Usuario(
            nome_completo="Manuel Antunes",
            email="manuel@exemplo.pt",
            telefone="+351912345678",
            tipo=TipoUsuario.PACIENTE,
            fuso_horario="Europe/Lisbon",
        )

        db.add_all([psicologa, paciente])
        db.commit()

        # Recarregando para obter os IDs gerados
        db.refresh(psicologa)
        db.refresh(paciente)

        print(f"-> Psicóloga cadastrada: ID {psicologa.id} - Fuso: {psicologa.fuso_horario}")
        print(f"-> Paciente cadastrado: ID {paciente.id} - Fuso: {paciente.fuso_horario}\n")

        print("3. Agendando uma Consulta...")
        # Cenário: Agendamos uma consulta para amanhã às 14:00 no fuso de São Paulo.
        # Precisamos converter isso para UTC ANTES de salvar no banco!
        fuso_sp = ZoneInfo("America/Sao_Paulo")
        horario_sp = datetime.now(fuso_sp).replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)

        # Convertendo para UTC:
        horario_utc_inicio = horario_sp.astimezone(timezone.utc)
        horario_utc_fim = horario_utc_inicio + timedelta(minutes=50) # Sessão padrão de 50min

        consulta = Consulta(
            paciente_id=paciente.id,
            psicologa_id=psicologa.id,
            data_hora_inicio=horario_utc_inicio,
            data_hora_fim=horario_utc_fim,
            status=StatusConsulta.AGENDADA,
            link_chamada="https://meet.google.com/exemplo-sala",
        )

        db.add(consulta)
        db.commit()
        db.refresh(consulta)

        print(f"-> Consulta agendada com ID {consulta.id}!")
        print(f"   [No Banco em UTC]: {consulta.data_hora_inicio.isoformat()}\n")

        print("4. Demonstração da Mágica dos Fusos Horários:")
        # Agora vamos ler do banco e mostrar como cada um enxergará o horário da sessão:
        # SQLite armazena como texto e pode devolver o datetime 'naive' (sem fuso acoplado).
        # Garantimos que ele seja reconhecido como UTC antes de converter:
        dt_utc = consulta.data_hora_inicio
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)

        fuso_paciente = ZoneInfo(consulta.paciente.fuso_horario)
        horario_visao_paciente = dt_utc.astimezone(fuso_paciente)

        fuso_psico = ZoneInfo(consulta.psicologa.fuso_horario)
        horario_visao_psico = dt_utc.astimezone(fuso_psico)

        print(f"   Horário para a Psicóloga (Brasil):   {horario_visao_psico.strftime('%d/%m/%Y às %H:%M (%Z)')}")
        print(f"   Horário para o Paciente (Portugal):  {horario_visao_paciente.strftime('%d/%m/%Y às %H:%M (%Z)')}")
        print("\n Ambos estarão na sala no exato mesmo instante, sem nenhuma confusão de horário!")


if __name__ == "__main__":
    main()
