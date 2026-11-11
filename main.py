from datetime import date, datetime, timedelta
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
    ConsultaReagendar,
    ConsultaResponse,
    LoginRequest,
    TokenResponse,
    VerificarPacienteRequest,
    VerificarPacienteResponse,
    PacienteRapidoCreate,
)
from security import (
    gerar_hash_senha,
    verificar_senha,
    criar_token_jwt,
    obter_usuario_logado,
)
from contextlib import asynccontextmanager
from regras_agendamento import (
    validar_regras_agendamento,
    obter_horarios_disponiveis,
)
from whatsapp_service import processar_lembrete_consulta
from scheduler import iniciar_agendador, parar_agendador, verificar_e_enviar_lembretes

# Garante que as tabelas existam no banco ao iniciar a aplicação
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização: liga o APScheduler para rodar em segundo plano
    iniciar_agendador()
    yield
    # Encerramento: desliga o scheduler com segurança
    parar_agendador()


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

app = FastAPI(
    title="Health Hub API",
    description="API de Agendamento de Consultas de Psicologia com Lembretes WhatsApp e LGPD",
    version="0.3.0",
    lifespan=lifespan
)

# Servindo arquivos estáticos (CSS, JS, imagens)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Rotas para entrega das páginas web
@app.get("/agendar", tags=["Frontend"], summary="Tela pública de agendamento do paciente")
def pagina_agendar():
    return FileResponse(STATIC_DIR / "agendar.html")


@app.get("/painel", tags=["Frontend"], summary="Painel administrativo da psicóloga")
def pagina_painel():
    return FileResponse(STATIC_DIR / "painel.html")


# ==============================================================================
# ENDPOINTS UTILITÁRIOS (METADADOS DE PAÍSES E FUSOS HORÁRIOS)
# ==============================================================================
import pycountry
from zoneinfo import available_timezones

# Cache em memória para resposta instantânea
TODOS_PAISES = sorted(
    [{"codigo": p.alpha_2, "nome": p.name} for p in pycountry.countries if hasattr(p, "alpha_2")],
    key=lambda x: x["nome"]
)

TODOS_FUSOS = sorted(list(available_timezones()))


@app.get(
    "/util/paises",
    tags=["Utilidades"],
    summary="Listar todos os países do mundo (ISO 3166-1 alpha-2)"
)
def listar_todos_paises():
    """Retorna lista com todos os países cadastrados no padrão internacional."""
    return TODOS_PAISES


@app.get(
    "/util/fusos",
    tags=["Utilidades"],
    summary="Listar todos os fusos horários do planeta (padrão IANA)"
)
def listar_todos_fusos():
    """Retorna lista com todos os identificadores IANA de fusos horários."""
    return TODOS_FUSOS




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

    # Criptografando a senha com bcrypt antes de salvar no banco
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
# FLUXO DE PACIENTES ATIVOS (ABORDAGEM 2: LISTA DE PACIENTES DA CLÍNICA)
# ==============================================================================

@app.post(
    "/pacientes/verificar",
    response_model=VerificarPacienteResponse,
    tags=["Pacientes"],
    summary="Verificar se o WhatsApp pertence a um paciente ativo pré-cadastrado"
)
def verificar_paciente_ativo(
    dados: VerificarPacienteRequest,
    db: Session = Depends(get_db)
):
    """
    Utilizado na tela pública de agendamento:
    O paciente digita seu WhatsApp. Se já for cadastrado pela psicóloga,
    libera a seleção de horários. Se não for, convida para uma triagem inicial.
    """
    telefone_formatado = valid_phone_number(dados.phone, dados.country)
    if not telefone_formatado:
        return VerificarPacienteResponse(
            ativo=False,
            mensagem="Número de telefone inválido. Verifique o DDD e os dígitos."
        )

    paciente = db.query(User).filter(
        User.phone == telefone_formatado,
        User.tipo == UserType.Paciente
    ).first()

    if not paciente:
        return VerificarPacienteResponse(
            ativo=False,
            mensagem=(
                "Você ainda não possui cadastro ativo nesta clínica. "
                "Para iniciar o acompanhamento, entre em contato diretamente pelo WhatsApp da psicóloga para uma breve conversa inicial!"
            )
        )

    return VerificarPacienteResponse(
        ativo=True,
        paciente_id=paciente.id,
        nome=paciente.full_name,
        time_zone=paciente.time_zone,
        mensagem=f"Bem-vindo(a) de volta, {paciente.full_name}! Selecione seu horário abaixo."
    )


@app.post(
    "/pacientes/cadastrar-rapido",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Pacientes"],
    summary="Psicóloga cadastra um novo paciente aprovado (Privado)"
)
def cadastrar_paciente_rapido(
    paciente_in: PacienteRapidoCreate,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    """
    Apenas a psicóloga autenticada pode cadastrar novos pacientes aprovados.
    Cria a conta do paciente com senha padrão temporária para uso futuro.
    """
    telefone_formatado = valid_phone_number(paciente_in.phone, paciente_in.country)
    if not telefone_formatado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Telefone inválido para o país '{paciente_in.country}'."
        )

    existente = db.query(User).filter(User.phone == telefone_formatado).first()
    if existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Já existe um paciente cadastrado com este número de telefone."
        )

    # Gera username automático baseado no primeiro nome + últimos dígitos do fone
    primeiro_nome = paciente_in.full_name.split()[0].lower()
    ultimos_digitos = telefone_formatado[-4:]
    username_gerado = f"{primeiro_nome}_{ultimos_digitos}"

    novo_paciente = User(
        tipo=UserType.Paciente,
        full_name=paciente_in.full_name,
        username=username_gerado,
        password_hash=gerar_hash_senha("senha_provisoria_123"),
        age=paciente_in.age,
        country=paciente_in.country,
        time_zone=paciente_in.time_zone,
        phone=telefone_formatado
    )

    db.add(novo_paciente)
    db.commit()
    db.refresh(novo_paciente)
    return novo_paciente


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

    # Valida todas as regras de negócio: antecedência mínima, dias úteis, horário comercial, hora cheia e anti-choque!
    data_hora_fim = validar_regras_agendamento(
        db=db,
        psicologa=psicologa,
        data_hora_inicio_solicitada=consulta_in.data_hora_inicio
    )

    link = consulta_in.link_reuniao or None # caso ainda não tenha link para a reunião

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


@app.patch(
    "/consultas/{consulta_id}/agendar",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Volta o status de uma consulta à AGENDADA caso tenha cancelado sem querer"
)
def agendar_novamente_consulta(
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
        
    consulta.status = Status.AGENDADA
    db.commit()
    db.refresh(consulta)
    return consulta


@app.get(
    "/horarios-disponiveis",
    response_model=List[datetime],
    tags=["Consultas"],
    summary="Consultar horários livres de uma psicóloga em uma data específica"
)
def listar_horarios_disponiveis(
    psicologa_id: int,
    dia: date = Query(..., description="Data no formato AAAA-MM-DD (ex: 2026-10-30)"),
    db: Session = Depends(get_db)
):
    """
    Retorna apenas os slots de horário que:
    1. Respeitam a antecedência mínima de 2 dias.
    2. Estão dentro do horário comercial (08:00 às 18:00) em dias úteis.
    3. NÃO possuem conflito com outras consultas ativas da psicóloga.
    """
    psicologa = db.query(User).filter(User.id == psicologa_id).first()
    if not psicologa or psicologa.tipo != UserType.Psicologo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Psicóloga com ID {psicologa_id} não foi encontrada."
        )

    return obter_horarios_disponiveis(db, psicologa, dia)


@app.patch(
    "/consultas/{consulta_id}/reagendar",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Reagendar uma consulta para um novo horário"
)
def reagendar_consulta(
    consulta_id: int,
    reagendar_in: ConsultaReagendar,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    """
    Reagenda uma consulta validando todas as regras no novo horário:
    - Minuto redondo (hora cheia).
    - Horário comercial e dia útil.
    - Antecedência mínima.
    - Anti-choque (sem conflitar com outras consultas da psicóloga).
    """
    consulta = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consulta com ID {consulta_id} não foi encontrada."
        )

    # Valida as regras para o novo horário (ignorando conflito com a própria consulta atual)
    nova_data_fim = validar_regras_agendamento(
        db=db,
        psicologa=consulta.psicologa,
        data_hora_inicio_solicitada=reagendar_in.data_hora_inicio,
        consulta_id_ignorar=consulta.id
    )

    consulta.data_hora_inicio = reagendar_in.data_hora_inicio
    consulta.data_hora_fim = nova_data_fim
    consulta.status = Status.AGENDADA
    db.commit()
    db.refresh(consulta)
    return consulta


@app.post(
    "/consultas/{consulta_id}/enviar-lembrete",
    response_model=ConsultaResponse,
    tags=["WhatsApp"],
    summary="Disparar manualmente o lembrete via WhatsApp para uma consulta"
)
def disparar_lembrete_manual(
    consulta_id: int,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    """
    Permite à psicóloga disparar o lembrete sob demanda pelo painel administrativo.
    Gera o texto com data/hora convertida no fuso do paciente e envia a mensagem.
    """
    consulta = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Consulta com ID {consulta_id} não foi encontrada."
        )

    if consulta.status != Status.AGENDADA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não é possível enviar lembrete para uma consulta com status '{consulta.status.value}'."
        )

    sucesso = processar_lembrete_consulta(consulta)
    if not sucesso:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Falha ao enviar mensagem de lembrete via WhatsApp."
        )

    consulta.lembrete_enviado = True
    db.commit()
    db.refresh(consulta)
    return consulta


@app.post(
    "/consultas/processar-lembretes-agora",
    tags=["WhatsApp"],
    summary="Executar imediatamente a verificação de lembretes pendentes das próximas 24h"
)
def executar_verificacao_lembretes_agora(
    usuario_logado: dict = Depends(obter_usuario_logado)
):
    """
    Aciona imediatamente a rotina do agendador em background
    para checar e enviar lembretes pendentes sem precisar aguardar os 30 minutos.
    """
    verificar_e_enviar_lembretes()
    return {"mensagem": "Rotina de verificação de lembretes executada com sucesso!"}