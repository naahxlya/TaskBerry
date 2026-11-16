from bson import ObjectId
from flask import Blueprint, render_template, session

from app.database.connection import get_database


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
def dashboard():

    db = get_database()

    usuario_id = session.get("usuario_id")

    # Busca os dados do usuário autenticado.
    usuario = None

    if usuario_id and ObjectId.is_valid(usuario_id):
        usuario = db["usuarios"].find_one({
            "_id": ObjectId(usuario_id)
        })

    # Recupera o nome do empreendimento cadastrado.
    empresa_nome = (
        usuario.get("negocio", "").strip()
        if usuario else ""
    )

    if not empresa_nome:
        empresa_nome = "Empreendimento não informado"

    # Conta os clientes pertencentes ao usuário.
    total_clientes = db["clientes"].count_documents({
        "usuario_id": usuario_id
    })

    return render_template(
        "dashboard.html",
        total_clientes=total_clientes,
        empresa_nome=empresa_nome
    )