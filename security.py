from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database.usermodel import User

# Configurações do Token JWT
# Em produção real (Módulo 7), moveremos essa chave para uma variável de ambiente (.env)
SECRET_KEY = "segredo_super_secreto_e_inviolavel_para_o_mvp_health_hub"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # O token valerá por 24 horas

# Esse esquema diz ao FastAPI onde o cliente deve ir para fazer login
# Isso adiciona aquele botão de cadeado "Authorize" automático no Swagger (/docs)!
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# ==============================================================================
# HASHING DE SENHAS (BCRYPT)
# ==============================================================================

def gerar_hash_senha(senha: str) -> str:
    """Transforma a senha em texto puro em um hash bcrypt unidirecional."""
    # O bcrypt trabalha com bytes, por isso usamos encode('utf-8')
    senha_bytes = senha.encode("utf-8")
    salt = bcrypt.gensalt()
    hash_bytes = bcrypt.hashpw(senha_bytes, salt)
    return hash_bytes.decode("utf-8")


def verificar_senha(senha_pura: str, senha_hash: str) -> bool:
    """Confere se a senha digitada corresponde ao hash gravado no banco."""
    return bcrypt.checkpw(
        senha_pura.encode("utf-8"),
        senha_hash.encode("utf-8")
    )


# ==============================================================================
# GERAÇÃO E VALIDAÇÃO DE TOKENS JWT
# ==============================================================================

def criar_token_jwt(dados: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Gera um Token JWT assinado contendo os dados do payload e data de expiração."""
    payload = dados.copy()
    
    if expires_delta:
        expiracao = datetime.now(timezone.utc) + expires_delta
    else:
        expiracao = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
    payload.update({"exp": expiracao})
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def decodificar_token_jwt(token: str) -> dict:
    """Decodifica e verifica a assinatura do token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O token de acesso expirou. Por favor, faça login novamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso inválido ou corrompido.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ==============================================================================
# DEPENDÊNCIA DE AUTENTICAÇÃO (O Guardião das Rotas Privadas)
# ==============================================================================

def obter_usuario_logado(
    token: str = Depends(oauth2_scheme)
) -> dict:
    """
    Lê o token JWT enviado no cabeçalho 'Authorization: Bearer <token>',
    valida a autenticidade e devolve os dados do usuário.
    """
    payload = decodificar_token_jwt(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido: identificador de usuário não encontrado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
