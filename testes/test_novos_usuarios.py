# para rodar esse arquivo é preciso roda-lo em "modulo" pois como importamos arquivos e classes da pasta database,mas estamos
# na pasta teste, o python não consegue achar o caminho para importar essas ferramentas, e por isso ira dar erro. 
# o certo é rodar no terminal, na raiz do projeto, e com o comando de modulo (-m): "uv run python -m testes.test_novos_usuarios"
# isso acontece porque isso não é um pytest, caso fosse, ja especifiquei no pyproject.toml a raiz do projeto para rodar apena "uv run pytest"

#type: ignore
"""
Passo 1.4: Teste prático de gravação e conversão de fuso horário.

O que este script faz:
1. Conecta no SQLite e garante que as tabelas 'users' e 'consultas' existam.
2. Cadastra a Psicóloga (no Brasil) e um Paciente (em Portugal).
3. Agenda uma consulta para amanhã às 14:00 (Horário de São Paulo).
4. O nosso TypeDecorator 'HorarioUTC' salva a data no banco convertida em UTC (17:00 UTC).
5. Lemos a consulta de volta do banco e exibimos no fuso de cada um.
"""
import sys
from pathlib import Path


from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from database.engine import Base, SessionLocal, engine
from database.usermodel import User, UserType
from database.consultas import Consultas, Status


def main():
    print("=" * 60)
    print(" PASSO 1.4: TESTANDO GRAVAÇÃO E FUSOS HORÁRIOS")
    print("=" * 60)

    # 1. Cria as tabelas se ainda não existirem
    print("\n[Etapa 1] Criando tabelas no banco de dados...")

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"não foi possível criar o banco de dados.\n\nErro:\n{e}")
        return

    print("✓ Tabelas verificadas e prontas!")

    # 2. Abre a sessão para falar com o banco
    with SessionLocal() as db:
        print("\n[Etapa 2] Cadastrando a psicóloga e o paciente...")

        # Limpando registros antigos de testes anteriores para não duplicar username/phone
        db.query(Consultas).delete()
        db.query(User).delete()
        db.commit()

        # Criando a psicóloga (em São Paulo)
        psicologa = User(
            tipo=UserType.Psicologo,
            full_name="Carolina Silva (Psicóloga)",
            username="carolina_psi",
            password_hash="hash_super_secreto_123",
            age=48,
            country="BR",
            time_zone="America/Sao_Paulo",
            phone="+5511988887777"
        )

        # Criando o paciente (em Lisboa, Portugal)
        paciente = User(
            tipo=UserType.Paciente,
            full_name="Manuel Antunes",
            username="manuel_pt",
            password_hash="hash_paciente_456",
            age=32,
            country="PT",
            time_zone="Europe/Lisbon",
            phone="+351912345678"
        )

        db.add_all([psicologa, paciente])
        db.commit()

        # db.refresh busca os IDs que o banco acabou de gerar e coloca na classe psicóloga
        db.refresh(psicologa)
        db.refresh(paciente)

        print(f"\n✓ Psicóloga cadastrada: {psicologa.full_name} (ID: {psicologa.id}, Fuso: {psicologa.time_zone})")
        print(f"✓ Paciente cadastrado:  {paciente.full_name} (ID: {paciente.id}, Fuso: {paciente.time_zone})")

        # 3. Agendando uma consulta
        print("\n[Etapa 3] Agendando consulta para amanhã às 14:00 (Horário de São Paulo)...")

        # Criando a data consciente do fuso de São Paulo
        fuso_sp = ZoneInfo(psicologa.time_zone)
        inicio_sp = datetime.now(fuso_sp).replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1)
        fim_sp = inicio_sp + timedelta(minutes=50) # Sessão padrão de 50 minutos

        nova_consulta = Consultas(
            psicologa_id=psicologa.id,
            paciente_id=paciente.id,
            data_hora_inicio=inicio_sp, # Passamos no fuso de SP; o HorarioUTC cuidará de converter para UTC!
            data_hora_fim=fim_sp,
            status=Status.AGENDADA,
            link_reuniao="https://meet.google.com/exemplo-sala"
        )

        db.add(nova_consulta)
        db.commit()
        db.refresh(nova_consulta)

        print(f"✓ Consulta agendada com sucesso! ID: {nova_consulta.id}")

        # 4. Verificação dos Fusos Horários
        print("\n" + "=" * 60)
        print(" DEMONSTRAÇÃO PRÁTICA DOS FUSOS HORÁRIOS")
        print("=" * 60)

        # Buscamos a consulta salva no banco
        consulta_banco = db.query(Consultas).filter(Consultas.id == nova_consulta.id).first()

        print(f"\n-> Como está gravado no Banco de Dados (UTC):")
        print(f"   Início: {consulta_banco.data_hora_inicio} ({consulta_banco.data_hora_inicio.tzinfo})")
        print(f"   Fim:    {consulta_banco.data_hora_fim} ({consulta_banco.data_hora_fim.tzinfo})\n")

        # Convertendo para o fuso da psicóloga e paciente de forma 100% limpa e direta
        visao_psicologa = consulta_banco.data_hora_inicio.astimezone(ZoneInfo(consulta_banco.psicologa.time_zone))
        visao_paciente = consulta_banco.data_hora_inicio.astimezone(ZoneInfo(consulta_banco.paciente.time_zone))

        print(f"-> Como a Psicóloga vê no painel dela (Brasil):")
        print(f"   Data: {visao_psicologa.strftime('%d/%m/%Y às %H:%M')} (Fuso: {visao_psicologa.tzname()})")

        print(f"\n-> Como o Paciente vê na confirmação/WhatsApp (Portugal):")
        print(f"   Data: {visao_paciente.strftime('%d/%m/%Y às %H:%M')} (Fuso: {visao_paciente.tzname()})")

        print("\n" + "=" * 60)
        print(" Conclusão: Ambos entrarão no Google Meet exatamente no mesmo")
        print(" instante, cada um no seu respectivo horário local!")
        print("=" * 60)


if __name__ == "__main__":
    main()
