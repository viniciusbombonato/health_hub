import engine 
from enum import Enum as PyEnum
import pycountry
from zoneinfo import available_timezones
from sqlalchemy import  String, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, MappedColumn, relationship

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

class user(engine.Base):
    __tablename__ = "users"

    id: Mapped[int] = MappedColumn(primary_key=True)

    # Usei o SQLEnum para indicar para o banco de dados que isso é um Enum e tem valores fixos definidos em UserType 
    # Porém talvez não funcione com sqlite
    tipo: Mapped[UserType] = MappedColumn(SQLEnum(UserType, native_enum = False), nullable = False, index = True)

    full_name: Mapped[str] 
    username: Mapped[str] = MappedColumn(String(30), nullable = False, unique = True, index = True)
    password_hash: Mapped[str]
    age: Mapped[int] = MappedColumn(Integer, nullable = False)

    #Esse Enum contém dicionários com todos os paises {BR: 'Brazil'}, e fuso horários
    country: Mapped[str] = MappedColumn(SQLEnum(CountriesEnums, native_enum = False), nullable = False) # type: ignore
    time_zone: Mapped[str] = MappedColumn(SQLEnum(TimeZonesEnums, native_enum = False), nullable = False) # type: ignore
   
    phone: Mapped[str] = MappedColumn(String(30), nullable = False, unique = True, index = True)

    #relacionamento entre tabelas
    consultas_como_paciente: Mapped[list["Consultas"]] = relationship(
        "Consultas",
        foreign_keys = "[Consultas.paciente_id]"",
        back_populates = "paciente"
    )

    consultas_como_pscicologa: Mapped[list["Consultas"]] = relationship(
        "Consultas",
        foreign_keys = "[Consultas.pscicologa_id]",
        back_populates = "psicologa"
    )