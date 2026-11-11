"""
Módulo de Agendamento em Segundo Plano (Background Scheduler).
Utiliza o APScheduler para verificar periodicamente consultas que
acontecerão nas próximas 24 horas e ainda não receberam lembrete.
"""
from datetime import datetime, timedelta, timezone
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from database.engine import SessionLocal
from database.consultas import Consultas, Status
from whatsapp_service import processar_lembrete_consulta

logger = logging.getLogger("health_hub.scheduler")

# Instância única do agendador em background
scheduler = BackgroundScheduler()


def verificar_e_enviar_lembretes():
    """
    Job periódico executado pelo APScheduler.
    Busca no banco consultas ativas que ocorrem nas próximas 24 horas
    e que ainda possuem lembrete_enviado == False.
    """
    print("\n⏰ [SCHEDULER] Verificando consultas que precisam de lembrete...")

    with SessionLocal() as db:
        agora_utc = datetime.now(timezone.utc)
        limite_24h_utc = agora_utc + timedelta(hours=24)

        # Buscamos consultas agendadas entre agora e as próximas 24h
        consultas_pendentes = db.query(Consultas).filter(
            Consultas.status == Status.AGENDADA,
            Consultas.lembrete_enviado == False,
            Consultas.data_hora_inicio >= agora_utc,
            Consultas.data_hora_inicio <= limite_24h_utc
        ).all()

        if not consultas_pendentes:
            print("⏰ [SCHEDULER] Nenhuma consulta pendente de lembrete no momento.")
            return

        print(f"⏰ [SCHEDULER] Encontradas {len(consultas_pendentes)} consulta(s) para enviar lembrete!")

        for consulta in consultas_pendentes:
            try:
                enviado = processar_lembrete_consulta(consulta)
                if enviado:
                    consulta.lembrete_enviado = True
                    db.commit()
                    print(f"✓ Lembrete marcado como enviado para a consulta #{consulta.id} ({consulta.paciente.full_name})")
            except Exception as e:
                db.rollback()
                print(f"❌ Erro ao enviar lembrete da consulta #{consulta.id}: {e}")
                logger.error(f"Falha ao enviar lembrete para consulta #{consulta.id}: {e}")


def iniciar_agendador():
    """
    Inicia o APScheduler com um job recorrente a cada 30 minutos.
    Pode ser chamado no evento de startup do FastAPI.
    """
    if not scheduler.running:
        # Executa a verificação a cada 30 minutos
        scheduler.add_job(
            verificar_e_enviar_lembretes,
            "interval",
            minutes=30,
            id="job_lembretes_whatsapp",
            replace_existing=True
        )
        scheduler.start()
        print("🚀 [SCHEDULER] APScheduler iniciado com sucesso (intervalo: 30 minutos)!")


def parar_agendador():
    """Para o agendador de forma limpa no encerramento da API."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("🛑 [SCHEDULER] APScheduler finalizado.")
