from datetime import timedelta
from typing import List, Optional
import phonenumbers
from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database.engine import Base, SessionLocal, engine
from database.usermodel import User, UserType
from database.consultas import Consultas, Status
from schemas import (
    UserCreate,
    UserResponse,
    ConsultaCreate,
    ConsultaResponse,
    LoginRequest,
    TokenResponse,
)
from security import (
    gerar_hash_senha,
    verificar_senha,
    criar_token_jwt,
    obter_usuario_logado,
)

# Garante que as tabelas existam no banco ao iniciar a aplicação
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Health Hub API",
    description="API de Agendamento de Consultas de Psicologia com Autenticação e LGPD",
    version="0.2.0"
)


# ==============================================================================
# DEPENDÊNCIA DO BANCO DE DADOS
# ==============================================================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==============================================================================
# FUNÇÃO DE VALIDAÇÃO DE TELEFONE
# ==============================================================================
def valid_phone_number(phone: str, country_alpha2: str = "BR") -> str | None:
    try:
        validation = phonenumbers.parse(phone, country_alpha2)
        if phonenumbers.is_valid_number(validation):
            return phonenumbers.format_number(validation, phonenumbers.PhoneNumberFormat.E164)
        return None
    except phonenumbers.NumberParseException:
        return None


# ==============================================================================
# ROTAS GERAIS E AUTENTICAÇÃO (LOGIN)
# ==============================================================================
@app.get("/", tags=["Geral"])
def root():
    return {"mensagem": "Bem-vindo ao Health Hub API!"}


@app.post(
    "/login",
    response_model=TokenResponse,
    tags=["Autenticação"],
    summary="Login da psicóloga/usuário (OAuth2 Form para o Swagger)"
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Recebe username e password, valida o hash bcrypt e devolve o Token JWT.
    Compatível com o botão 'Authorize' (cadeado) do Swagger UI (/docs).
    """
    usuario = db.query(User).filter(User.username == form_data.username).first()
    
    if not usuario or not verificar_senha(form_data.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nome de usuário ou senha incorretos.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Gera o crachá digital (Token JWT)
    token = criar_token_jwt(dados={"sub": usuario.username, "tipo": usuario.tipo.value})
    return {"access_token": token, "token_type": "bearer"}


@app.post(
    "/login-json",
    response_model=TokenResponse,
    tags=["Autenticação"],
    summary="Login via JSON (para aplicações frontend e mobile)"
)
def login_json(
    login_in: LoginRequest,
    db: Session = Depends(get_db)
):
    """Permite login enviando um corpo JSON comum (útil para frontend React/Vue/mobile)."""
    usuario = db.query(User).filter(User.username == login_in.username).first()
    
    if not usuario or not verificar_senha(login_in.password, usuario.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nome de usuário ou senha incorretos."
        )

    token = criar_token_jwt(dados={"sub": usuario.username, "tipo": usuario.tipo.value})
    return {"access_token": token, "token_type": "bearer"}


@app.get(
    "/me",
    response_model=UserResponse,
    tags=["Autenticação"],
    summary="Obter dados do usuário atualmente autenticado"
)
def obter_perfil(
    payload: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    """Retorna os dados cadastrais da pessoa dona do token enviado."""
    username = payload.get("sub")
    usuario = db.query(User).filter(User.username == username).first()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")
    return usuario


# ==============================================================================
# ROTAS DE USUÁRIOS
# ==============================================================================
@app.post(
    "/usuarios",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Usuários"],
    summary="Cadastrar um novo usuário (Psicóloga ou Paciente)"
)
def cadastrar_usuario(usuario_in: UserCreate, db: Session = Depends(get_db)):
    telefone_formatado = valid_phone_number(usuario_in.phone, usuario_in.country)
    if not telefone_formatado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Número de telefone inválido para o país '{usuario_in.country}'."
        )

    usuario_existente = db.query(User).filter(
        (User.username == usuario_in.username) | (User.phone == telefone_formatado)
    ).first()
    
    if usuario_existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um usuário cadastrado com este username ou telefone."
        )

    # SEGURANÇA REAL: Criptografando a senha com bcrypt antes de salvar no banco!
    senha_criptografada = gerar_hash_senha(usuario_in.password)

    novo_usuario = User(
        tipo=usuario_in.tipo,
        full_name=usuario_in.full_name,
        username=usuario_in.username,
        password_hash=senha_criptografada,
        age=usuario_in.age,
        country=usuario_in.country,
        time_zone=usuario_in.time_zone,
        phone=telefone_formatado
    )

    db.add(novo_usuario)
    db.commit()
    db.refresh(novo_usuario)
    return novo_usuario


@app.get(
    "/usuarios",
    response_model=List[UserResponse],
    tags=["Usuários"],
    summary="Listar todos os usuários cadastrados"
)
def listar_usuarios(db: Session = Depends(get_db)):
    return db.query(User).all()


@app.get(
    "/usuarios/{user_id}",
    response_model=UserResponse,
    tags=["Usuários"],
    summary="Buscar um usuário específico pelo ID"
)
def buscar_usuario(user_id: int, db: Session = Depends(get_db)):
    usuario = db.query(User).filter(User.id == user_id).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuário com ID {user_id} não foi encontrado."
        )
    return usuario


# ==============================================================================
# ROTAS DE CONSULTAS
# ==============================================================================
@app.post(
    "/consultas",
    response_model=ConsultaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Consultas"],
    summary="Agendar uma nova consulta (Público para pacientes)"
)
def agendar_consulta(consulta_in: ConsultaCreate, db: Session = Depends(get_db)):
    psicologa = db.query(User).filter(User.id == consulta_in.psicologa_id).first()
    if not psicologa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Psicóloga com ID {consulta_in.psicologa_id} não foi encontrada."
        )
    if psicologa.tipo != UserType.Psicologo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O usuário de ID {consulta_in.psicologa_id} não é uma psicóloga."
        )

    paciente = db.query(User).filter(User.id == consulta_in.paciente_id).first()
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paciente com ID {consulta_in.paciente_id} não foi encontrado."
        )
    if paciente.tipo != UserType.Paciente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"O usuário de ID {consulta_in.paciente_id} não é um paciente."
        )

    # Duração padrão de 50 minutos
    duracao_padrao = timedelta(minutes=50)
    data_hora_fim = consulta_in.data_hora_inicio + duracao_padrao

    link = consulta_in.link_reuniao or "https://meet.google.com/exemplo-sala"

    nova_consulta = Consultas(
        psicologa_id=consulta_in.psicologa_id,
        paciente_id=consulta_in.paciente_id,
        data_hora_inicio=consulta_in.data_hora_inicio,
        data_hora_fim=data_hora_fim,
        status=Status.AGENDADA,
        link_reuniao=link
    )

    db.add(nova_consulta)
    db.commit()
    db.refresh(nova_consulta)

    return nova_consulta


@app.get(
    "/consultas",
    response_model=List[ConsultaResponse],
    tags=["Consultas"],
    summary="Listar consultas agendadas (Protegido por Autenticação)"
)
def listar_consultas(
    paciente_id: Optional[int] = Query(None, description="Filtrar por ID do paciente"),
    psicologa_id: Optional[int] = Query(None, description="Filtrar por ID da psicóloga"),
    usuario_logado: dict = Depends(obter_usuario_logado),  # Rota protegida! Exige Token JWT válido
    db: Session = Depends(get_db)
):
    """
    Esta rota agora é PRIVADA:
    Apenas usuários autenticados (portadores de um token JWT válido) conseguem ver a lista de consultas.
    """
    query = db.query(Consultas)
    
    if paciente_id:
        query = query.filter(Consultas.paciente_id == paciente_id)
    if psicologa_id:
        query = query.filter(Consultas.psicologa_id == psicologa_id)
        
    return query.all()


@app.get(
    "/consultas/{consulta_id}",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Buscar detalhes de uma consulta específica"
)
def buscar_consulta(
    consulta_id: int,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    consulta = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consulta com ID {consulta_id} não foi encontrada."
        )
    return consulta


@app.patch(
    "/consultas/{consulta_id}/cancelar",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Cancelar uma consulta agendada"
)
def cancelar_consulta(
    consulta_id: int,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    consulta = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consulta com ID {consulta_id} não foi encontrada."
        )
        
    consulta.status = Status.CANCELADA
    db.commit()
    db.refresh(consulta)
    return consulta
