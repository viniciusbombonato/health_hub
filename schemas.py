from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from database.usermodel import UserType
from database.consultas import Status


# ==============================================================================
# SCHEMAS DE USUÁRIO (Psicóloga e Pacientes)
# ==============================================================================

class UserBase(BaseModel):
    """Campos compartilhados que todo usuário tem."""
    full_name: str = Field(..., min_length=2, max_length=120, description="Nome completo")
    username: str = Field(..., min_length=3, max_length=30, description="Nome de usuário único")
    age: int = Field(..., gt=0, lt=130, description="Idade válida")
    phone: str = Field(..., description="Telefone com DDI e DDD (ex: +5511999998888)")
    country: str = Field(default="BR", description="Código do país ou nome (ex: BR, PT)")
    time_zone: str = Field(default="America/Sao_Paulo", description="Fuso horário IANA válido")


class UserCreate(UserBase):
    """
    Schema de ENTRADA: O que o usuário envia para se cadastrar.
    Recebe a senha em texto puro digitada no formulário.
    """
    password: str = Field(..., min_length=6, description="Senha de no mínimo 6 caracteres")
    tipo: UserType = Field(default=UserType.Paciente, description="Tipo de usuário (paciente ou psicologo)")


class UserResponse(UserBase):
    """
    Schema de SAÍDA: O que a API devolve para a internet.
    ATENÇÃO: A senha NUNCA é devolvida aqui por segurança!
    """
    id: int
    tipo: UserType

    # Permite ler objetos do SQLAlchemy diretamente
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# SCHEMAS DE CONSULTA
# ==============================================================================

class ConsultaCreate(BaseModel):
    """
    Schema de ENTRADA para agendamento de uma sessão.
    O cliente informa quem é o paciente, a psicóloga e a data/hora de início.
    """
    paciente_id: int
    psicologa_id: int
    data_hora_inicio: datetime = Field(..., description="Data e hora com fuso horário (ex: 2026-10-23T14:00:00-03:00)")
    link_reuniao: Optional[str] = Field(default=None, description="Link do Google Meet ou Zoom")


class ConsultaReagendar(BaseModel):
    """Schema para alteração do horário de uma consulta."""
    data_hora_inicio: datetime = Field(..., description="Novo horário de início desejado (ex: 2026-10-30T10:00:00-03:00)")


class ConsultaResponse(BaseModel):
    """
    Schema de SAÍDA: O que o cliente/painel recebe de volta.
    """
    id: int
    paciente_id: int
    psicologa_id: int
    data_hora_inicio: datetime
    data_hora_fim: datetime
    status: Status
    link_reuniao: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# SCHEMAS DE AUTENTICAÇÃO (LOGIN & TOKENS)
# ==============================================================================

class LoginRequest(BaseModel):
    """Schema para autenticação enviando JSON."""
    username: str = Field(..., description="Nome de usuário")
    password: str = Field(..., description="Senha em texto puro")


class TokenResponse(BaseModel):
    """Resposta com o Token JWT devolvida após login bem-sucedido."""
    access_token: str
    token_type: str = "bearer"

