import re
import smtplib
import ssl

from datetime import datetime, timezone
from email.message import EmailMessage

from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    url_for,
    flash,  
    session
)

from itsdangerous import (
    URLSafeTimedSerializer,
    SignatureExpired,
    BadSignature
)

from pymongo.errors import (
    DuplicateKeyError,
    ServerSelectionTimeoutError
)

from werkzeug.security import generate_password_hash, check_password_hash

from app.database.connection import get_database


# ==========================================
# CONFIGURAÇÃO DAS ROTAS
# ==========================================

auth_bp = Blueprint("auth", __name__)


# ==========================================
# LOGIN DE USUÁRIOS
# ==========================================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")

        if not email or not senha:
            flash("Informe seu e-mail e sua senha.", "danger")
            return render_template("login.html")

        try:
            db = get_database()
            usuarios = db["usuarios"]

            usuario = usuarios.find_one({
                "email": email
            })

            if usuario and check_password_hash(
                usuario["senha"],
                senha
            ):

                if not usuario.get("ativo", True):
                    flash("Esta conta está desativada.", "warning")
                    return render_template("login.html")

                session.clear()
                session["usuario_id"] = str(usuario["_id"])
                session["usuario_nome"] = usuario["nome"]
                session["usuario_email"] = usuario["email"]

                return redirect(url_for("dashboard.dashboard"))

            flash("E-mail ou senha incorretos.", "danger")

        except Exception:
            current_app.logger.exception("Erro durante o login.")
            flash(
                "Não foi possível realizar o login. Tente novamente.",
                "danger"
            )

    return render_template("login.html")



# ==========================================
# CADASTRO DE USUÁRIOS
# ==========================================

@auth_bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():

    if request.method == "POST":

        nome = request.form.get("nome", "").strip()
        negocio = request.form.get("negocio", "").strip()
        email = request.form.get("email", "").strip().lower()
        telefone = request.form.get("telefone", "").strip()
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")
        termos = request.form.get("termos")

        # Verifica campos obrigatórios
        if not all([
            nome,
            negocio,
            email,
            telefone,
            senha,
            confirmar_senha
        ]):
            flash("Preencha todos os campos obrigatórios.", "danger")
            return render_template("cadastro.html")

        # Validação básica do e-mail
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            flash("Informe um endereço de e-mail válido.", "danger")
            return render_template("cadastro.html")

        # Verifica o tamanho da senha
        if len(senha) < 8:
            flash(
                "A senha precisa ter pelo menos 8 caracteres.",
                "danger"
            )
            return render_template("cadastro.html")

        # Confirma se as senhas são iguais
        if senha != confirmar_senha:
            flash("As senhas não coincidem.", "danger")
            return render_template("cadastro.html")

        # Verifica o aceite dos termos
        if not termos:
            flash(
                "Você precisa aceitar os termos para continuar.",
                "danger"
            )
            return render_template("cadastro.html")

        try:
            db = get_database()
            usuarios = db["usuarios"]

            # Impede o cadastro de e-mails duplicados
            usuarios.create_index("email", unique=True)

            usuario = {
                "nome": nome,
                "negocio": negocio,
                "email": email,
                "telefone": telefone,
                "senha": generate_password_hash(senha),
                "criado_em": datetime.now(timezone.utc),
                "ativo": True
            }

            usuarios.insert_one(usuario)

            flash(
                "Conta criada com sucesso! Agora você já pode entrar.",
                "success"
            )

            return redirect(url_for("inicio"))

        except DuplicateKeyError:
            flash("Este e-mail já está cadastrado.", "warning")

        except ServerSelectionTimeoutError:
            flash(
                "Não foi possível conectar ao MongoDB. "
                "Verifique se o banco está iniciado.",
                "danger"
            )

        except Exception:
            current_app.logger.exception(
                "Erro ao realizar cadastro."
            )

            flash(
                "Ocorreu um erro ao criar sua conta. Tente novamente.",
                "danger"
            )

    return render_template("cadastro.html")


# ==========================================
# GERAÇÃO E VALIDAÇÃO DOS TOKENS
# ==========================================

def gerar_token_recuperacao(email):

    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"]
    )

    token = serializer.dumps(
        email,
        salt="taskberry-recuperacao-senha"
    )

    return token


def verificar_token_recuperacao(token):

    serializer = URLSafeTimedSerializer(
        current_app.config["SECRET_KEY"]
    )

    try:
        email = serializer.loads(
            token,
            salt="taskberry-recuperacao-senha",
            max_age=1800
        )

        return email

    except (SignatureExpired, BadSignature):
        return None


# ==========================================
# ENVIO DO E-MAIL DE RECUPERAÇÃO
# ==========================================

def enviar_email_recuperacao(destinatario, link):

    mensagem = EmailMessage()

    mensagem["Subject"] = "Recuperação de senha | TaskBerry"

    mensagem["From"] = current_app.config["MAIL_DEFAULT_SENDER"]

    mensagem["To"] = destinatario

    mensagem.set_content(f"""
Olá!

Recebemos uma solicitação para redefinir a senha da sua conta TaskBerry.

Para criar uma nova senha, acesse o link abaixo:

{link}

Este link é válido por 30 minutos.

Se você não solicitou essa alteração, ignore este e-mail.

Equipe TaskBerry
""")

    contexto = ssl.create_default_context()

    with smtplib.SMTP(
        current_app.config["MAIL_SERVER"],
        current_app.config["MAIL_PORT"]
    ) as servidor:

        servidor.starttls(context=contexto)

        servidor.login(
            current_app.config["MAIL_USERNAME"],
            current_app.config["MAIL_PASSWORD"]
        )

        servidor.send_message(mensagem)


# ==========================================
# SOLICITAÇÃO DE RECUPERAÇÃO DE SENHA
# ==========================================

@auth_bp.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()

        if email:

            try:
                db = get_database()
                usuarios = db["usuarios"]

                usuario = usuarios.find_one({
                    "email": email
                })

                if usuario:

                    token = gerar_token_recuperacao(email)

                    link = url_for(
                        "auth.redefinir_senha",
                        token=token,
                        _external=True
                    )

                    enviar_email_recuperacao(
                        email,
                        link
                    )

            except Exception:
                current_app.logger.exception(
                    "Erro ao processar recuperação de senha."
                )

        flash(
            "Se o e-mail estiver cadastrado, você receberá "
            "as instruções de recuperação.",
            "info"
        )

        return redirect(url_for("auth.recuperar_senha"))

    return render_template("recuperar_senha.html")


# ==========================================
# REDEFINIÇÃO DE SENHA
# ==========================================

@auth_bp.route(
    "/redefinir-senha/<token>",
    methods=["GET", "POST"]
)
def redefinir_senha(token):

    email = verificar_token_recuperacao(token)

    # Verifica se o token é válido
    if not email:

        return render_template(
            "redefinir_senha.html",
            token_valido=False
        )

    if request.method == "POST":

        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        # Validação do tamanho da senha
        if len(senha) < 8:

            flash(
                "A senha precisa ter pelo menos 8 caracteres.",
                "danger"
            )

        # Confirmação das senhas
        elif senha != confirmar_senha:

            flash(
                "As senhas não coincidem.",
                "danger"
            )

        else:

            try:
                db = get_database()
                usuarios = db["usuarios"]

                resultado = usuarios.update_one(
                    {"email": email},
                    {
                        "$set": {
                            "senha": generate_password_hash(senha)
                        }
                    }
                )

                if resultado.modified_count:

                    flash(
                        "Senha alterada com sucesso! "
                        "Faça login com sua nova senha.",
                        "success"
                    )

                    return redirect(url_for("inicio"))

                flash(
                    "Não foi possível alterar a senha. "
                    "Solicite um novo link.",
                    "danger"
                )

                return redirect(
                    url_for("auth.recuperar_senha")
                )

            except Exception:
                current_app.logger.exception(
                    "Erro ao redefinir senha."
                )

                flash(
                    "Ocorreu um erro ao alterar sua senha.",
                    "danger"
                )

    return render_template(
        "redefinir_senha.html",
        token_valido=True
    )


# ==========================================
# ENCERRAR SESSÃO
# ==========================================

@auth_bp.route("/logout", methods=["POST"])
def logout():

    session.clear()

    flash(
        "Você saiu da sua conta com segurança.",
        "success"
    )

    return redirect(url_for("inicio"))
