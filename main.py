import os
from datetime import date, datetime, timedelta
from typing import List, Optional
import phonenumbers
from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from database.engine import Base, SessionLocal, engine
from database.usermodel import User, UserType, RecorrenciaTipo
from database.consultas import Consultas, Status
from schemas import (
    UserCreate,
    UserResponse,
    UserUpdate,
    PacienteTabelaItem,
    ConsultaComPacienteResponse,
    AlterarSenhaRequest,
    ConsultaCreate,
    ConsultaReagendar,
    ConsultaResponse,
    LoginRequest,
    TokenResponse,
    VerificarPacienteRequest,
    VerificarPacienteResponse,
    ProximaConsultaInfo,
    PacienteRapidoCreate,
    ConfigurarRecorrenciaRequest,
    RecusarConsultaRequest,
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
    gerar_consultas_recorrentes,
)
from whatsapp_service import processar_lembrete_consulta, processar_notificacao_status
from scheduler import iniciar_agendador, parar_agendador, verificar_e_enviar_lembretes

# Garante que as tabelas existam no banco ao iniciar a aplicação
Base.metadata.create_all(bind=engine)


def criar_psicologa_inicial():
    """Cria a psicóloga inicial caso não exista nenhuma no banco e as variáveis de ambiente estejam definidas."""
    admin_username = os.getenv("ADMIN_USERNAME")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_phone = os.getenv("ADMIN_PHONE")

    if not admin_username or not admin_password or not admin_phone:
        return

    db = SessionLocal()
    try:
        psicologa_existente = db.query(User).filter(User.tipo == UserType.Psicologo).first()
        if psicologa_existente:
            return

        admin_country = os.getenv("ADMIN_COUNTRY", "BR")
        telefone_formatado = valid_phone_number(admin_phone, admin_country) or admin_phone

        nova_psicologa = User(
            tipo=UserType.Psicologo,
            full_name=os.getenv("ADMIN_FULL_NAME", "Dra. Carolina Silva"),
            username=admin_username,
            password_hash=gerar_hash_senha(admin_password),
            age=int(os.getenv("ADMIN_AGE", "30")),
            country=admin_country,
            time_zone=os.getenv("ADMIN_TIME_ZONE", "America/Sao_Paulo"),
            phone=telefone_formatado,
        )
        db.add(nova_psicologa)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização: garante psicóloga inicial (se configurada) e liga o APScheduler
    criar_psicologa_inicial()
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
@app.get("/", tags=["Frontend"], summary="Página inicial pública (Home)")
def pagina_home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/painel-psicologo", tags=["Frontend"], summary="Painel de gestão da psicóloga")
def pagina_painel_psicologo():
    return FileResponse(STATIC_DIR / "painel_psicologo.html")


@app.get("/painel-paciente", tags=["Frontend"], summary="Área do paciente")
def pagina_painel_paciente():
    return FileResponse(STATIC_DIR / "painel_paciente.html")


@app.get("/login", tags=["Frontend"], summary="Página de login")
def pagina_login_view():
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/cadastro-inicial", tags=["Frontend"], summary="Cadastro inicial de psicólogo")
def pagina_cadastro_inicial():
    return FileResponse(STATIC_DIR / "register_psicologa.html")


# Aliases para compatibilidade retroativa
@app.get("/agendar", tags=["Frontend"], include_in_schema=False)
def redirect_agendar():
    return FileResponse(STATIC_DIR / "painel_paciente.html")


@app.get("/painel", tags=["Frontend"], include_in_schema=False)
def redirect_painel():
    return FileResponse(STATIC_DIR / "painel_psicologo.html")


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
@app.get("/api/status", tags=["Geral"], summary="Status da API")
def api_status():
    return {"status": "online", "mensagem": "Health Hub API operacional!"}


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
        phone=telefone_formatado,
        ativo=usuario_in.ativo,
        tipo_recorrencia=usuario_in.tipo_recorrencia,
        dia_semana_fixo=usuario_in.dia_semana_fixo,
        horario_fixo=usuario_in.horario_fixo
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


@app.patch(
    "/usuarios/{user_id}",
    response_model=UserResponse,
    tags=["Usuários"],
    summary="Atualizar dados de um usuário (Psicóloga ou o próprio usuário)"
)
def atualizar_usuario(
    user_id: int,
    dados: UserUpdate,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    usuario = db.query(User).filter(User.id == user_id).first()
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuário com ID {user_id} não foi encontrado."
        )

    # Verifica permissão: apenas a psicóloga ou o próprio usuário
    solicitante = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if not solicitante or (solicitante.tipo != UserType.Psicologo and solicitante.id != user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para editar este usuário."
        )

    if dados.full_name is not None:
        usuario.full_name = dados.full_name
    if dados.age is not None:
        usuario.age = dados.age
    if dados.country is not None:
        usuario.country = dados.country
    if dados.time_zone is not None:
        usuario.time_zone = dados.time_zone
    if dados.ativo is not None:
        usuario.ativo = dados.ativo
    if dados.tipo_recorrencia is not None:
        usuario.tipo_recorrencia = dados.tipo_recorrencia
    if dados.dia_semana_fixo is not None:
        usuario.dia_semana_fixo = dados.dia_semana_fixo
    if dados.horario_fixo is not None:
        usuario.horario_fixo = dados.horario_fixo

    if dados.phone is not None:
        tel_formatado = valid_phone_number(dados.phone, dados.country or usuario.country)
        if not tel_formatado:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Número de telefone inválido."
            )
        # Verifica se já pertence a outro usuário
        conflito_tel = db.query(User).filter(User.phone == tel_formatado, User.id != user_id).first()
        if conflito_tel:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este número de telefone já está cadastrado para outro usuário."
            )
        usuario.phone = tel_formatado

    db.commit()
    db.refresh(usuario)
    return usuario


@app.post(
    "/usuarios/alterar-senha",
    tags=["Usuários"],
    summary="Alterar senha do usuário logado"
)
def alterar_senha(
    dados: AlterarSenhaRequest,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    usuario = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")

    if not verificar_senha(dados.senha_atual, usuario.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta.")

    usuario.password_hash = gerar_hash_senha(dados.nova_senha)
    db.commit()
    return {"mensagem": "Senha alterada com sucesso!"}


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

    # Busca a próxima consulta ativa (confirmada ou pendente) do paciente
    agora_utc = datetime.now(timedelta(0))
    proxima = db.query(Consultas).filter(
        Consultas.paciente_id == paciente.id,
        Consultas.status.in_([Status.CONFIRMADA, Status.PENDENTE_APROVACAO]),
        Consultas.data_hora_inicio >= datetime.now(paciente.consultas_como_paciente[0].data_hora_inicio.tzinfo if paciente.consultas_como_paciente else None).astimezone(timedelta(0)) if False else Consultas.data_hora_fim >= datetime.now(Consultas.data_hora_inicio.type.impl.python_type if hasattr(Consultas.data_hora_inicio.type, 'impl') else None) if False else Consultas.data_hora_inicio >= datetime.utcnow()
    ).order_by(Consultas.data_hora_inicio.asc()).first()

    proxima_info = None
    if proxima:
        proxima_info = ProximaConsultaInfo(
            id=proxima.id,
            data_hora_inicio=proxima.data_hora_inicio,
            data_hora_fim=proxima.data_hora_fim,
            status=proxima.status,
            link_reuniao=proxima.link_reuniao
        )

    return VerificarPacienteResponse(
        ativo=paciente.ativo,
        paciente_id=paciente.id,
        nome=paciente.full_name,
        time_zone=paciente.time_zone,
        tipo_recorrencia=paciente.tipo_recorrencia,
        dia_semana_fixo=paciente.dia_semana_fixo,
        horario_fixo=paciente.horario_fixo,
        proxima_consulta=proxima_info,
        mensagem=f"Bem-vindo(a) de volta, {paciente.full_name}!"
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
    Permite definir o horário fixo e recorrência e já gerar automaticamente as consultas na agenda!
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

    primeiro_nome = paciente_in.full_name.split()[0].lower()
    ultimos_digitos = telefone_formatado[-4:]
    username_gerado = f"{primeiro_nome}_{ultimos_digitos}"

    novo_paciente = User(
        tipo=UserType.Paciente,
        full_name=paciente_in.full_name,
        username=username_gerado,
        password_hash=gerar_hash_senha("123456"),
        age=paciente_in.age,
        country=paciente_in.country,
        time_zone=paciente_in.time_zone,
        phone=telefone_formatado,
        ativo=True,
        tipo_recorrencia=paciente_in.tipo_recorrencia,
        dia_semana_fixo=paciente_in.dia_semana_fixo,
        horario_fixo=paciente_in.horario_fixo
    )

    db.add(novo_paciente)
    db.commit()
    db.refresh(novo_paciente)

    # Se a psicóloga já informou dia e horário fixo, gera as consultas futuras automaticamente
    if novo_paciente.dia_semana_fixo is not None and novo_paciente.horario_fixo:
        psicologa = db.query(User).filter(User.username == usuario_logado["sub"]).first()
        if psicologa:
            gerar_consultas_recorrentes(db, psicologa, novo_paciente, quantidade_semanas=8)

    return novo_paciente


@app.post(
    "/pacientes/{paciente_id}/configurar-recorrencia",
    response_model=UserResponse,
    tags=["Pacientes"],
    summary="Psicóloga define ou altera o horário e frequência recorrente do paciente"
)
def configurar_recorrencia_paciente(
    paciente_id: int,
    dados: ConfigurarRecorrenciaRequest,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    paciente = db.query(User).filter(User.id == paciente_id, User.tipo == UserType.Paciente).first()
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente não encontrado."
        )

    psicologa = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if not psicologa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Psicóloga não encontrada."
        )

    paciente.tipo_recorrencia = dados.tipo_recorrencia
    paciente.dia_semana_fixo = dados.dia_semana_fixo
    paciente.horario_fixo = dados.horario_fixo
    db.commit()
    db.refresh(paciente)

    # Gera as consultas automáticas para as semanas escolhidas
    gerar_consultas_recorrentes(
        db=db,
        psicologa=psicologa,
        paciente=paciente,
        quantidade_semanas=dados.gerar_semanas
    )

    return paciente


@app.get(
    "/pacientes/meus",
    response_model=List[PacienteTabelaItem],
    tags=["Pacientes"],
    summary="Listar todos os pacientes com status de notificação para a tabela do psicólogo"
)
def listar_meus_pacientes(
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    psicologa = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if not psicologa or psicologa.tipo != UserType.Psicologo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito à psicóloga.")

    pacientes = db.query(User).filter(User.tipo == UserType.Paciente).all()
    resultado = []

    for pac in pacientes:
        # Verifica se há alguma notificação pendente (consulta pendente ou reagendamento)
        notif = None
        consulta_pendente = db.query(Consultas).filter(
            Consultas.paciente_id == pac.id,
            Consultas.status == Status.PENDENTE_APROVACAO
        ).first()

        if consulta_pendente:
            if consulta_pendente.reagendamento_de_id:
                notif = "Pedido de remarcação pendente"
            else:
                notif = "Nova sessão pendente de aprovação"
        else:
            # Verifica cancelamento recente nas últimas 24h
            cancelada_recente = db.query(Consultas).filter(
                Consultas.paciente_id == pac.id,
                Consultas.status == Status.CANCELADA,
                Consultas.data_hora_inicio >= datetime.utcnow()
            ).first()
            if cancelada_recente:
                notif = "Consulta futura cancelada"

        resultado.append(PacienteTabelaItem(
            id=pac.id,
            full_name=pac.full_name,
            phone=pac.phone,
            ativo=pac.ativo,
            tipo_recorrencia=pac.tipo_recorrencia,
            horario_fixo=pac.horario_fixo,
            dia_semana_fixo=pac.dia_semana_fixo,
            notificacao=notif,
            age=pac.age,
            country=pac.country,
            time_zone=pac.time_zone,
            username=pac.username
        ))

    return resultado


@app.get(
    "/pacientes/{paciente_id}/consultas-futuras",
    response_model=List[ConsultaResponse],
    tags=["Pacientes"],
    summary="Listar consultas futuras de um paciente"
)
def listar_consultas_futuras_paciente(
    paciente_id: int,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    agora_utc = datetime.now(timezone.utc)
    consultas = db.query(Consultas).filter(
        Consultas.paciente_id == paciente_id,
        Consultas.status.in_([Status.CONFIRMADA, Status.PENDENTE_APROVACAO]),
        Consultas.data_hora_inicio >= agora_utc
    ).order_by(Consultas.data_hora_inicio.asc()).all()
    return consultas


@app.post(
    "/pacientes/{paciente_id}/remarcar-recorrencia",
    response_model=UserResponse,
    tags=["Pacientes"],
    summary="Paciente remarca sua recorrência fixa (cancela futuras e gera novas)"
)
def paciente_remarcar_recorrencia(
    paciente_id: int,
    dados: ConfigurarRecorrenciaRequest,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    paciente = db.query(User).filter(User.id == paciente_id, User.tipo == UserType.Paciente).first()
    if not paciente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente não encontrado.")

    # Busca a psicóloga padrão ou associada
    psicologa = db.query(User).filter(User.tipo == UserType.Psicologo).first()
    if not psicologa:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Psicóloga não encontrada no sistema.")

    # Cancela as consultas futuras geradas da recorrência anterior
    agora_utc = datetime.now(timezone.utc)
    futuras = db.query(Consultas).filter(
        Consultas.paciente_id == paciente_id,
        Consultas.status == Status.CONFIRMADA,
        Consultas.data_hora_inicio >= agora_utc + timedelta(hours=24)
    ).all()
    for c in futuras:
        c.status = Status.CANCELADA

    paciente.tipo_recorrencia = dados.tipo_recorrencia
    paciente.dia_semana_fixo = dados.dia_semana_fixo
    paciente.horario_fixo = dados.horario_fixo
    db.commit()
    db.refresh(paciente)

    gerar_consultas_recorrentes(
        db=db,
        psicologa=psicologa,
        paciente=paciente,
        quantidade_semanas=dados.gerar_semanas
    )

    return paciente


# ==============================================================================
# ROTAS DE CONSULTAS
# ==============================================================================
@app.post(
    "/consultas",
    response_model=ConsultaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Consultas"],
    summary="Solicitar ou agendar uma consulta (Público ou Psicóloga)"
)
def agendar_consulta(
    consulta_in: ConsultaCreate,
    db: Session = Depends(get_db)
):
    psicologa = db.query(User).filter(User.id == consulta_in.psicologa_id).first()
    if not psicologa or psicologa.tipo != UserType.Psicologo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Psicóloga inválida."
        )

    paciente = db.query(User).filter(User.id == consulta_in.paciente_id).first()
    if not paciente or paciente.tipo != UserType.Paciente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Paciente inválido."
        )

    # Paciente marcando pelo link público: EXIGE antecedência mínima de 2 dias!
    data_hora_fim = validar_regras_agendamento(
        db=db,
        psicologa=psicologa,
        data_hora_inicio_solicitada=consulta_in.data_hora_inicio,
        exigir_antecedencia=True
    )

    link = consulta_in.link_reuniao or None

    # Toda sessão solicitada pelo paciente entra como PENDENTE DE APROVAÇÃO pela psicóloga
    nova_consulta = Consultas(
        psicologa_id=consulta_in.psicologa_id,
        paciente_id=consulta_in.paciente_id,
        data_hora_inicio=consulta_in.data_hora_inicio,
        data_hora_fim=data_hora_fim,
        status=Status.PENDENTE_APROVACAO,
        link_reuniao=link
    )

    db.add(nova_consulta)
    db.commit()
    db.refresh(nova_consulta)

    return nova_consulta


@app.post(
    "/consultas/agendar-imediato",
    response_model=ConsultaResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Consultas"],
    summary="Psicóloga agenda consulta direta sem restrição de 2 dias de antecedência (Privado)"
)
def agendar_consulta_psicologa(
    consulta_in: ConsultaCreate,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    psicologa = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if not psicologa or psicologa.tipo != UserType.Psicologo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas psicólogas podem realizar agendamentos diretos."
        )

    paciente = db.query(User).filter(User.id == consulta_in.paciente_id).first()
    if not paciente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Paciente não encontrado."
        )

    # Psicóloga agendando: NÃO exige os 2 dias de antecedência!
    data_hora_fim = validar_regras_agendamento(
        db=db,
        psicologa=psicologa,
        data_hora_inicio_solicitada=consulta_in.data_hora_inicio,
        exigir_antecedencia=False
    )

    nova_consulta = Consultas(
        psicologa_id=psicologa.id,
        paciente_id=paciente.id,
        data_hora_inicio=consulta_in.data_hora_inicio,
        data_hora_fim=data_hora_fim,
        status=Status.CONFIRMADA,
        link_reuniao=consulta_in.link_reuniao
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
    status_filtro: Optional[Status] = Query(None, description="Filtrar por Status"),
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    query = db.query(Consultas)
    if paciente_id:
        query = query.filter(Consultas.paciente_id == paciente_id)
    if psicologa_id:
        query = query.filter(Consultas.psicologa_id == psicologa_id)
    if status_filtro:
        query = query.filter(Consultas.status == status_filtro)
    return query.order_by(Consultas.data_hora_inicio.asc()).all()


@app.patch(
    "/consultas/{consulta_id}/aprovar",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Psicóloga aprova a consulta solicitada ou pedido de troca (Privado)"
)
def aprovar_consulta(
    consulta_id: int,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    consulta = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consulta não encontrada."
        )

    # Se esta consulta for um pedido de troca de uma consulta anterior
    if consulta.reagendamento_de_id:
        consulta_antiga = db.query(Consultas).filter(Consultas.id == consulta.reagendamento_de_id).first()
        if consulta_antiga:
            consulta_antiga.status = Status.CANCELADA

    consulta.status = Status.CONFIRMADA
    db.commit()
    db.refresh(consulta)

    # Dispara mensagem WhatsApp informando a aprovação
    try:
        processar_notificacao_status(consulta, aprovado=True)
    except Exception as e:
        print(f"Erro ao notificar WhatsApp: {e}")

    return consulta


@app.patch(
    "/consultas/{consulta_id}/recusar",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Psicóloga recusa o horário solicitado pelo paciente (Privado)"
)
def recusar_consulta(
    consulta_id: int,
    dados: RecusarConsultaRequest,
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    consulta = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consulta não encontrada."
        )

    consulta.status = Status.RECUSADA
    consulta.justificativa_recusa = dados.justificativa
    db.commit()
    db.refresh(consulta)

    # Dispara mensagem WhatsApp informando a recusa
    try:
        processar_notificacao_status(consulta, aprovado=False, justificativa=dados.justificativa)
    except Exception as e:
        print(f"Erro ao notificar WhatsApp: {e}")

    return consulta


@app.post(
    "/consultas/{consulta_id}/solicitar-troca",
    response_model=ConsultaResponse,
    tags=["Consultas"],
    summary="Paciente solicita troca de horário da sua consulta (Exige 2 dias de antecedência)"
)
def solicitar_troca_consulta(
    consulta_id: int,
    reagendar_in: ConsultaReagendar,
    db: Session = Depends(get_db)
):
    consulta_atual = db.query(Consultas).filter(Consultas.id == consulta_id).first()
    if not consulta_atual:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consulta não encontrada."
        )

    # Paciente solicitando troca: EXIGE antecedência mínima de 2 dias!
    nova_data_fim = validar_regras_agendamento(
        db=db,
        psicologa=consulta_atual.psicologa,
        data_hora_inicio_solicitada=reagendar_in.data_hora_inicio,
        consulta_id_ignorar=consulta_atual.id,
        exigir_antecedencia=True
    )

    # Cria uma nova solicitação pendente vinculada à anterior
    solicitacao_troca = Consultas(
        psicologa_id=consulta_atual.psicologa_id,
        paciente_id=consulta_atual.paciente_id,
        data_hora_inicio=reagendar_in.data_hora_inicio,
        data_hora_fim=nova_data_fim,
        status=Status.PENDENTE_APROVACAO,
        reagendamento_de_id=consulta_atual.id,
        link_reuniao=consulta_atual.link_reuniao
    )

    db.add(solicitacao_troca)
    db.commit()
    db.refresh(solicitacao_troca)
    return solicitacao_troca


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

    usuario = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if usuario and usuario.tipo == UserType.Paciente:
        # Validação de antecedência de 24 horas para o paciente
        agora_utc = datetime.now(timezone.utc)
        limite_minimo = agora_utc + timedelta(hours=24)
        if consulta.data_hora_inicio < limite_minimo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cancelamentos pelo paciente exigem no mínimo 24 horas de antecedência."
            )

    consulta.status = Status.CANCELADA
    db.commit()
    db.refresh(consulta)
    return consulta


@app.get(
    "/consultas/semana",
    response_model=List[ConsultaComPacienteResponse],
    tags=["Consultas"],
    summary="Listar consultas de uma semana específica (Segunda a Domingo) com dados do paciente"
)
def listar_consultas_semana(
    semana_inicio: date = Query(..., description="Data da segunda-feira no formato AAAA-MM-DD"),
    usuario_logado: dict = Depends(obter_usuario_logado),
    db: Session = Depends(get_db)
):
    psicologa = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    if not psicologa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuário não encontrado.")

    from zoneinfo import ZoneInfo
    fuso_psicologa = ZoneInfo(psicologa.time_zone if psicologa.tipo == UserType.Psicologo else "America/Sao_Paulo")

    inicio_semana = datetime.combine(semana_inicio, time.min, tzinfo=fuso_psicologa)
    fim_semana = datetime.combine(semana_inicio + timedelta(days=7), time.min, tzinfo=fuso_psicologa)

    query = db.query(Consultas).filter(
        Consultas.data_hora_inicio >= inicio_semana,
        Consultas.data_hora_inicio < fim_semana
    )
    if psicologa.tipo == UserType.Psicologo:
        query = query.filter(Consultas.psicologa_id == psicologa.id)

    consultas = query.order_by(Consultas.data_hora_inicio.asc()).all()
    return consultas


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
        
    consulta.status = Status.CONFIRMADA
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

    # Valida se o paciente logado está reagendando e checa antecedência de 24h na consulta atual
    usuario = db.query(User).filter(User.username == usuario_logado["sub"]).first()
    exigir_antecedencia = True
    if usuario and usuario.tipo == UserType.Psicologo:
        exigir_antecedencia = False
    else:
        agora_utc = datetime.now(timezone.utc)
        if consulta.data_hora_inicio < agora_utc + timedelta(hours=24):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Remarcações pelo paciente exigem no mínimo 24 horas de antecedência."
            )

    # Valida as regras para o novo horário (ignorando conflito com a própria consulta atual)
    nova_data_fim = validar_regras_agendamento(
        db=db,
        psicologa=consulta.psicologa,
        data_hora_inicio_solicitada=reagendar_in.data_hora_inicio,
        consulta_id_ignorar=consulta.id,
        exigir_antecedencia=exigir_antecedencia
    )

    consulta.data_hora_inicio = reagendar_in.data_hora_inicio
    consulta.data_hora_fim = nova_data_fim
    consulta.status = Status.CONFIRMADA
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

    if consulta.status != Status.CONFIRMADA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não é possível enviar lembrete para uma consulta com status '{consulta.status.value}'. Apenas consultas confirmadas recebem lembrete."
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