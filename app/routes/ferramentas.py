from flask import Blueprint, render_template

ferramentas_bp = Blueprint("ferramentas", __name__)


@ferramentas_bp.route("/ferramentas")
def listar_ferramentas():
    return render_template("ferramentas.html")