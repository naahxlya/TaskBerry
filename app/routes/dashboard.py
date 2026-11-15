from flask import Blueprint, render_template, session

from app.database.connection import get_database


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
def dashboard():

    db = get_database()

    total_clientes = db["clientes"].count_documents({
        "usuario_id": session.get("usuario_id")
    })

    return render_template(
        "dashboard.html",
        total_clientes=total_clientes
    )