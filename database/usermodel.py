import engine 
from enum import Enum as PyEnum
import pycountry
from zoneinfo import available_timezones
from sqlalchemy import  String, Integer, Enum as SQLEnum
from sqlalchemy.orm import Mapped, MappedColumn
from sqlalchemy.types import TypeDecorator

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
    tipo: Mapped[UserType] = MappedColumn(SQLEnum(UserType, native_enum = False), nullable = False)

    full_name: Mapped[str] 
    username: Mapped[str] = MappedColumn(String(30), nullable = False)
    password_hash: Mapped[str]
    age: Mapped[int] = MappedColumn(Integer, nullable = False)

    #Esse Enum contém dicionários com todos os paises {BR: 'Brazil'}, e fuso horários
    country: Mapped[str] = MappedColumn(SQLEnum(CountriesEnums, native_enum = False), nullable = False) # type: ignore
    time_zone: Mapped[str] = MappedColumn(SQLEnum(TimeZonesEnums, native_enum = False), nullable = False) # type: ignore
   
    phone: Mapped[str]