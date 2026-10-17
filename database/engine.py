from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

engine = create_engine("sqlite+pysqlite///health_hub.db", echo=True)

class Base(DeclarativeBase):
    pass




