from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from config import settings

# 1. Pega a URL de conexão das configurações
database_url = settings.DATABASE_URL

# Ajuste automático comum no Render/Heroku (que fornecem postgres:// em vez de postgresql://)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://") and not database_url.startswith("postgresql+"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

# 2. Configurações específicas para cada tipo de banco
connect_args = {}
if database_url.startswith("sqlite"):
    # Necessário exclusivamente no SQLite para threads do FastAPI
    connect_args = {"check_same_thread": False}

engine = create_engine(
    database_url,
    echo=False,  # Em produção deixamos False para não poluir os logs
    connect_args=connect_args
)

# Fábrica de sessões para abrir conversas com o banco de dados
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass
