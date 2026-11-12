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


from config import settings
import httpx

def enviar_mensagem_whatsapp(telefone: str, mensagem: str) -> bool:
    """
    Camada de Envio Desacoplada (Adapter).
    
    1. Se as variáveis da Evolution API estiverem no .env / nuvem:
       - Faz o disparo HTTP real para o WhatsApp!
    2. Se não estiverem configuradas (desenvolvimento local):
       - Simula o envio logando no terminal com destaque.
    """
    if settings.EVOLUTION_API_URL and settings.EVOLUTION_API_KEY and settings.EVOLUTION_INSTANCE:
        try:
            url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{settings.EVOLUTION_INSTANCE}"
            headers = {
                "apikey": settings.EVOLUTION_API_KEY,
                "Content-Type": "application/json"
            }
            # Remove o '+' para o padrão de número da Evolution API
            numero_limpo = telefone.replace("+", "").replace(" ", "").replace("-", "")
            payload = {
                "number": numero_limpo,
                "text": mensagem
            }
            resposta = httpx.post(url, json=payload, headers=headers, timeout=10.0)
            if resposta.status_code in (200, 201):
                logger.info(f"Mensagem WhatsApp enviada com sucesso via Evolution API para {telefone}")
                return True
            else:
                logger.error(f"Erro ao enviar via Evolution API ({resposta.status_code}): {resposta.text}")
                return False
        except Exception as e:
            logger.error(f"Exceção de rede na Evolution API: {e}")
            return False

    # Modo Simulação Local (Dev)
    print("\n" + "📱 " + "=" * 56)
    print(" [WHATSAPP SIMULADOR DE ENVIO]")
    print(f" Para: {telefone}")
    print("-" * 58)
    print(mensagem)
    print("=" * 58 + "\n")

    logger.info(f"Lembrete WhatsApp simulado com sucesso para {telefone}")
    return True


def formatar_mensagem_aprovacao(consulta: Consultas) -> str:
    """Mensagem de confirmação enviada quando a psicóloga aprova a sessão."""
    paciente = consulta.paciente
    psicologa = consulta.psicologa
    fuso_paciente = ZoneInfo(paciente.time_zone)
    horario_local = consulta.data_hora_inicio.astimezone(fuso_paciente)

    data_formatada = horario_local.strftime("%d/%m/%Y")
    hora_formatada = horario_local.strftime("%H:%M")
    nome_fuso = horario_local.tzname()

    return (
        f"Olá, {paciente.full_name}! ✨\n\n"
        f"Sua sessão com a psicóloga {psicologa.full_name} foi CONFIRMADA!\n"
        f"📅 Data: {data_formatada}\n"
        f"⏰ Horário: {hora_formatada} ({nome_fuso})\n\n"
        f"Nos vemos em breve!"
    )


def formatar_mensagem_recusa(consulta: Consultas, justificativa: str | None = None) -> str:
    """Mensagem enviada se a psicóloga não puder no horário solicitado."""
    paciente = consulta.paciente
    psicologa = consulta.psicologa
    motivo = f"\nMotivo: {justificativa}" if justificativa else ""

    return (
        f"Olá, {paciente.full_name}.\n\n"
        f"A psicóloga {psicologa.full_name} não pôde aprovar o horário solicitado.{motivo}\n\n"
        f"Por favor, acesse o link de agendamento para escolher outro dia ou entre em contato diretamente pelo WhatsApp."
    )


def processar_notificacao_status(consulta: Consultas, aprovado: bool, justificativa: str | None = None) -> bool:
    """Dispara mensagem informando paciente sobre aprovação ou recusa do horário."""
    if aprovado:
        msg = formatar_mensagem_aprovacao(consulta)
    else:
        msg = formatar_mensagem_recusa(consulta, justificativa)
    return enviar_mensagem_whatsapp(consulta.paciente.phone, msg)


def processar_lembrete_consulta(consulta: Consultas) -> bool:
    """
    Gera o texto contextualizado e dispara o envio do lembrete periódico.
    """
    mensagem = formatar_mensagem_lembrete(consulta)
    sucesso = enviar_mensagem_whatsapp(
        telefone=consulta.paciente.phone,
        mensagem=mensagem
    )
    return sucesso


