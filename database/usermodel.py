#type: ignore
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base


class UserType(PyEnum):
    Psicologo = "psicologo"
    Paciente = "paciente"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Papel do usuário no sistema
    tipo: Mapped[UserType] = mapped_column(SQLEnum(UserType, native_enum=False), nullable=False, index=True)

    full_name: Mapped[str] 
    username: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    password_hash: Mapped[str]
    age: Mapped[int] = mapped_column(Integer, nullable=False)

    # Simplificado: strings diretas sem Enums gigantes
    country: Mapped[str] = mapped_column(String(50), nullable=False)
    time_zone: Mapped[str] = mapped_column(String(50), default="America/Sao_Paulo", nullable=False)
   
    phone: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)

    # Relacionamento entre tabelas
    consultas_como_paciente: Mapped[list["Consultas"]] = relationship(
        "Consultas",
        foreign_keys="[Consultas.paciente_id]",
        back_populates="paciente"
    )

    consultas_como_psicologa: Mapped[list["Consultas"]] = relationship(
        "Consultas",
        foreign_keys="[Consultas.psicologa_id]",
        back_populates="psicologa"
    )