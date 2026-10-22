from enum import Enum as PyEnum
from zoneinfo import available_timezones
import pycountry
from sqlalchemy import String, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.engine import Base

class UserType(PyEnum):
    Psicologo = "psicologo"
    Paciente = "paciente"

CountriesEnums = PyEnum(
    "CountriesEnums",
    {country.alpha_2: country.name for country in pycountry.countries}
) 

TimeZonesEnums = PyEnum(
    "TimeZonesEnums",
    {tz.replace("-", "_").replace("/", "_"): tz for tz in available_timezones()}
)

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Usei o SQLEnum para indicar para o banco de dados que isso é um Enum e tem valores fixos definidos em UserType 
    tipo: Mapped[UserType] = mapped_column(SQLEnum(UserType, native_enum=False), nullable=False, index=True)

    full_name: Mapped[str] 
    username: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    password_hash: Mapped[str]
    age: Mapped[int] = mapped_column(Integer, nullable=False)

    # Enums com os países e fusos
    country: Mapped[str] = mapped_column(SQLEnum(CountriesEnums, native_enum=False), nullable=False) # type: ignore
    time_zone: Mapped[str] = mapped_column(SQLEnum(TimeZonesEnums, native_enum=False), nullable=False) # type: ignore
   
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