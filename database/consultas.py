from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from database.engine import Base


class HorarioUTC(TypeDecorator):
    """
    Garante que qualquer data salva seja convertida para UTC
    e que qualquer data lida do SQLite receba o fuso UTC de volta.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # Quando o dado vai do Python para o Banco de Dados
        if value is not None:
            if value.tzinfo is None:
                # Se veio sem fuso, assume UTC
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        # Quando o dado sai do Banco para o Python
        if value is not None:
            if value.tzinfo is None:
                # Se o SQLite tirou o fuso, recolocamos UTC à força
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return value


class Status(PyEnum):
    AGENDADA = "agendada"
    REALIZADA = "realizada"
    CANCELADA = "cancelada"


class Consultas(Base):
    __tablename__ = "consultas"

    id: Mapped[int] = mapped_column(primary_key=True)

    psicologa_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    data_hora_inicio: Mapped[datetime] = mapped_column(HorarioUTC, index=True, nullable=False)
    data_hora_fim: Mapped[datetime] = mapped_column(HorarioUTC, index=True, nullable=False)

    status: Mapped[Status] = mapped_column(SQLEnum(Status, native_enum=False), default=Status.AGENDADA, index=True, nullable=False)
    link_reuniao: Mapped[str] = mapped_column(String(500), nullable=True)

    lembrete_enviado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relacionamento de tabelas
    psicologa = relationship("User", foreign_keys=[psicologa_id], back_populates="consultas_como_psicologa")
    paciente = relationship("User", foreign_keys=[paciente_id], back_populates="consultas_como_paciente")