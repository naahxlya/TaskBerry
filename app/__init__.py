import os

from flask import Flask, render_template, redirect, url_for, session, request
from dotenv import load_dotenv


def create_app():
    load_dotenv()

    app = Flask(__name__)

    # Configurações gerais
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

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

    # Proteção global das páginas internas
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

        return None

    return app