import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configurações centralizadas da aplicação.
    Lê valores do arquivo .env ou das variáveis de ambiente da nuvem.
    Se não houver valor configurado, utiliza os padrões seguros de desenvolvimento.
    """
    # Banco de Dados: SQLite local por padrão, PostgreSQL na nuvem
    DATABASE_URL: str = "sqlite:///health_hub.db"

    # Segurança e Autenticação JWT
    SECRET_KEY: str = "segredo_super_secreto_e_inviolavel_para_o_mvp_health_hub_dev_key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 horas

    # Integração WhatsApp (Evolution API / Provedor Real para o Módulo 7)
    EVOLUTION_API_URL: str = ""
    EVOLUTION_API_KEY: str = ""
    EVOLUTION_INSTANCE: str = ""

    # Permite ler arquivo .env na raiz do projeto (se existir)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
