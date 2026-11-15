from flask import Blueprint, render_template

chamados_bp = Blueprint("chamados", __name__)


@chamados_bp.route("/chamados")
def listar_chamados():
    return render_template("chamados.html")