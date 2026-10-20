import engine
from enum import Enum as PyEnum
from datetime import datetime, timezone
from sqlalchemy import  String, Integer, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, MappedColumn, relationship
from sqlalchemy.types import TypeDecorator

class HorarioUTC(TypeDecorator):

    impl = DateTime(tzinfo = True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                # Se veio sem fuso, assume UTC
                value = value.replace(timezone=timezone.utc)
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
    REALIZADA = "REALIZADA"

class Consultas(engine.Base):
    __tablename__ = "consultas"

    id: Mapped[int] = MappedColumn(primary_key = True)

    pscicologa_id: Mapped[int] = MappedColumn(ForeignKey("users.id"), nullable = False)
    paciente_id: Mapped[int] = MappedColumn(ForeignKey("users.id"), nullable = False)

    data_hora_inicio: Mapped[datetime] = MappedColumn(HorarioUTC, index = True, nullable = False)
    data_hora_fim: Mapped[datetime] = MappedColumn(HorarioUTC, index = True, nullable = False)

    status: Mapped[str] = MappedColumn(SQLEnum(Status), default = Status.AGENDADA, index = True, nullable = False)
    link_reuniao: Mapped[str] = MappedColumn(String(500), nullable = True)

    #relacionamento de tabelas
    pscicologa = relationship("user", foreign_keys = [pscicologa_id], back_populates = "consultas_como_pscicologa")
    paciente = relationship("user", foreign_keys = [paciente_id], back_populates = "consultas_como_paciente")