import logging
from zoneinfo import ZoneInfo
from database.consultas import Consultas

logger = logging.getLogger("health_hub.whatsapp")


def formatar_mensagem_lembrete(consulta: Consultas) -> str:
    """
    Monta a mensagem de lembrete personalizada e contextualizada
    no fuso horário exato do paciente!
    """
    paciente = consulta.paciente
    psicologa = consulta.psicologa

    # 1. Converte o horário em UTC armazenado no banco para o fuso do paciente
    fuso_paciente = ZoneInfo(paciente.time_zone)
    horario_local_paciente = consulta.data_hora_inicio.astimezone(fuso_paciente)

    data_formatada = horario_local_paciente.strftime("%d/%m/%Y")
    hora_formatada = horario_local_paciente.strftime("%H:%M")
    nome_fuso = horario_local_paciente.tzname()

    link_info = f"\n🔗 Link de atendimento: {consulta.link_reuniao}" if consulta.link_reuniao else ""

    mensagem = (
        f"Olá, {paciente.full_name}! 👋\n\n"
        f"Este é um lembrete da sua sessão com a psicóloga {psicologa.full_name}.\n"
        f"📅 Data: {data_formatada}\n"
        f"⏰ Horário: {hora_formatada} ({nome_fuso})\n"
        f"{link_info}\n\n"
        f"Caso precise reagendar com antecedência, entre em contato. Até logo!"
    )
    return mensagem


def enviar_mensagem_whatsapp(telefone: str, mensagem: str) -> bool:
    """
    Camada de Envio Desacoplada (Adapter).
    
    No MVP local:
      - Simula o envio logando no terminal com destaque para fácil verificação.
      - Retorna True simulando envio bem-sucedido.
      
    No ambiente de Produção:
      - Aqui basta plugar a chamada HTTP (requests/httpx) para a API real
        (Evolution API, Z-API, Twilio ou Meta Cloud API) usando tokens do .env.
    """
    print("\n" + "📱 " + "=" * 56)
    print(" [WHATSAPP SIMULADOR DE ENVIO]")
    print(f" Para: {telefone}")
    print("-" * 58)
    print(mensagem)
    print("=" * 58 + "\n")

    logger.info(f"Lembrete WhatsApp simulado com sucesso para {telefone}")
    return True


def processar_lembrete_consulta(consulta: Consultas) -> bool:
    """
    Gera o texto contextualizado e dispara o envio do lembrete.
    """
    mensagem = formatar_mensagem_lembrete(consulta)
    sucesso = enviar_mensagem_whatsapp(
        telefone=consulta.paciente.phone,
        mensagem=mensagem
    )
    return sucesso
