from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# URL de conexão: usando 3 barras para caminho relativo do SQLite
DATABASE_URL = "sqlite:///health_hub.db"

engine = create_engine(
    DATABASE_URL,
    echo=True,
    connect_args={"check_same_thread": False}  # Necessário para SQLite em ambiente multi-thread (como FastAPI)
)

# Fábrica de sessões para abrir conversas com o banco de dados
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass
