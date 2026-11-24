import os

from flask import Flask, render_template, redirect, url_for, session, request
from dotenv import load_dotenv
from bson import ObjectId
from werkzeug.security import check_password_hash
from flask import flash
from app.database.connection import get_database


def create_app():
    load_dotenv(override=True)

    print("MONGO_URI carregada:", bool(os.getenv("MONGO_URI")))
    print("MONGO_DB carregado:", os.getenv("MONGO_DB"))

    app = Flask(__name__)

    # Configurações gerais
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # até 12 MB por envio

    app.config["MONGO_URI"] = os.getenv(
        "MONGO_URI",
        "mongodb://localhost:27017/"
    )

    app.config["MONGO_DB"] = os.getenv(
        "MONGO_DB",
        "taskberry"
    )

    # Configurações de e-mail
    app.config["MAIL_SERVER"] = os.getenv(
        "MAIL_SERVER",
        "smtp.gmail.com"
    )

    app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", "587"))

    app.config["MAIL_USE_TLS"] = (
        os.getenv("MAIL_USE_TLS", "True").lower() == "true"
    )

    app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
    app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_DEFAULT_SENDER")

    # Registro das rotas
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.perfil import perfil_bp
    from app.routes.clientes import clientes_bp
    from app.routes.configuracoes import configuracoes_bp
    from app.routes.funcionarios import funcionarios_bp
    from app.routes.chamados import chamados_bp
    from app.routes.materiais import materiais_bp
    from app.routes.ferramentas import ferramentas_bp
    from app.routes.financeiro import financeiro_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(perfil_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(configuracoes_bp)
    app.register_blueprint(funcionarios_bp)
    app.register_blueprint(chamados_bp)
    app.register_blueprint(materiais_bp)
    app.register_blueprint(ferramentas_bp)
    app.register_blueprint(financeiro_bp)

    # Página inicial
    @app.route("/")
    def inicio():

        if session.get("usuario_id"):
            return redirect(url_for("dashboard.dashboard"))

        return render_template("login.html")

    @app.context_processor
    def disponibilizar_preferencias_globais():
        usuario_id = session.get("usuario_id")
        preferencias_padrao = {
            "incluir_clientes_arquivados_excluidos": False,
            "prioridade_chamados_primeiro": "urgente",
            "mostrar_botao_topo": True,
            "exigir_senha_exclusao": False,
            "ordem_clientes": "nome_asc",
            "ordem_funcionarios": "nome_asc",
            "ordem_materiais": "atualizado_desc"
        }
        if not usuario_id:
            return {"preferencias_taskberry": preferencias_padrao}
        try:
            configuracao = get_database()["configuracoes"].find_one(
                {"usuario_id": usuario_id}, {"preferencias": 1}
            ) or {}
            preferencias = {**preferencias_padrao, **configuracao.get("preferencias", {})}
        except Exception:
            preferencias = preferencias_padrao
        return {"preferencias_taskberry": preferencias}

    # Proteção global das páginas internas e confirmação opcional por senha.
    @app.before_request
    def proteger_paginas():

        endpoints_publicos = [
            "static",
            "inicio",
            "auth.login",
            "auth.cadastro",
            "auth.recuperar_senha",
            "auth.redefinir_senha",
            "auth.logout"
        ]

        if request.endpoint in endpoints_publicos:
            return None

        if not session.get("usuario_id"):
            return redirect(url_for("inicio"))

        # A senha é solicitada somente para exclusões permanentes.
        # Arquivar ou enviar um registro à lixeira continua usando apenas
        # a confirmação visual padrão do TaskBerry.
        endpoints_exclusao = {
            "clientes.excluir_permanentemente",
            "chamados.excluir_permanentemente",
            "materiais.excluir_material_permanentemente"
        }
        if request.method == "POST" and request.endpoint in endpoints_exclusao:
            configuracao = get_database()["configuracoes"].find_one(
                {"usuario_id": session.get("usuario_id")}, {"preferencias.exigir_senha_exclusao": 1}
            ) or {}
            exigir_senha = configuracao.get("preferencias", {}).get("exigir_senha_exclusao", False)
            if exigir_senha:
                senha_informada = request.form.get("senha_confirmacao", "")
                try:
                    usuario = get_database()["usuarios"].find_one({"_id": ObjectId(session["usuario_id"])})
                except Exception:
                    usuario = None
                if not usuario or not senha_informada or not check_password_hash(usuario.get("senha", ""), senha_informada):
                    flash("Senha incorreta. A exclusão não foi realizada.", "danger")
                    return redirect(request.referrer or url_for("dashboard.dashboard"))

        return None

    return app