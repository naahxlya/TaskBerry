from datetime import datetime, timezone
import re

from bson import ObjectId
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app
)

from app.database.connection import get_database


clientes_bp = Blueprint("clientes", __name__)


def obter_usuario_id():
    return session.get("usuario_id")


def buscar_cliente(cliente_id):
    """Busca um cliente pertencente ao usuário autenticado."""
    if not ObjectId.is_valid(cliente_id):
        return None

    db = get_database()

    return db["clientes"].find_one({
        "_id": ObjectId(cliente_id),
        "usuario_id": obter_usuario_id()
    })


@clientes_bp.route("/clientes")
def listar_clientes():
    db = get_database()
    colecao = db["clientes"]

    busca = request.args.get("busca", "").strip()

    filtro = {
        "usuario_id": obter_usuario_id()
    }

    if busca:
        termo = re.escape(busca)

        filtro["$or"] = [
            {"nome": {"$regex": termo, "$options": "i"}},
            {"telefone": {"$regex": termo, "$options": "i"}},
            {"email": {"$regex": termo, "$options": "i"}}
        ]

    clientes = list(
        colecao.find(filtro).sort("criado_em", -1)
    )

    total_clientes = colecao.count_documents({
        "usuario_id": obter_usuario_id()
    })

    return render_template(
        "clientes.html",
        clientes=clientes,
        busca=busca,
        total_clientes=total_clientes
    )


@clientes_bp.route("/clientes/novo", methods=["POST"])
def cadastrar_cliente():
    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip().lower()
    endereco = request.form.get("endereco", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    if not nome or not telefone:
        flash("Nome e telefone são obrigatórios.", "danger")
        return redirect(url_for("clientes.listar_clientes"))

    if email and ("@" not in email or "." not in email.split("@")[-1]):
        flash("Informe um e-mail válido.", "danger")
        return redirect(url_for("clientes.listar_clientes"))

    db = get_database()
    colecao = db["clientes"]

    if email:
        duplicado = colecao.find_one({
            "usuario_id": obter_usuario_id(),
            "email": email
        })

        if duplicado:
            flash("Este e-mail já está cadastrado.", "warning")
            return redirect(url_for("clientes.listar_clientes"))

    novo_cliente = {
        "usuario_id": obter_usuario_id(),
        "nome": nome,
        "telefone": telefone,
        "email": email,
        "endereco": endereco,
        "observacoes": observacoes,
        "total_servicos": 0,
        "criado_em": datetime.now(timezone.utc),
        "atualizado_em": datetime.now(timezone.utc)
    }

    try:
        colecao.insert_one(novo_cliente)
        flash("Cliente cadastrado com sucesso!", "success")

    except Exception:
        current_app.logger.exception("Erro ao cadastrar cliente.")
        flash("Não foi possível cadastrar o cliente.", "danger")

    return redirect(url_for("clientes.listar_clientes"))


@clientes_bp.route("/clientes/<cliente_id>/editar", methods=["POST"])
def editar_cliente(cliente_id):
    cliente = buscar_cliente(cliente_id)

    if not cliente:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("clientes.listar_clientes"))

    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip().lower()
    endereco = request.form.get("endereco", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    if not nome or not telefone:
        flash("Nome e telefone são obrigatórios.", "danger")
        return redirect(url_for("clientes.listar_clientes"))

    if email and ("@" not in email or "." not in email.split("@")[-1]):
        flash("Informe um e-mail válido.", "danger")
        return redirect(url_for("clientes.listar_clientes"))

    db = get_database()
    colecao = db["clientes"]

    if email:
        duplicado = colecao.find_one({
            "usuario_id": obter_usuario_id(),
            "email": email,
            "_id": {"$ne": ObjectId(cliente_id)}
        })

        if duplicado:
            flash("Este e-mail já pertence a outro cliente.", "warning")
            return redirect(url_for("clientes.listar_clientes"))

    try:
        colecao.update_one(
            {
                "_id": ObjectId(cliente_id),
                "usuario_id": obter_usuario_id()
            },
            {
                "$set": {
                    "nome": nome,
                    "telefone": telefone,
                    "email": email,
                    "endereco": endereco,
                    "observacoes": observacoes,
                    "atualizado_em": datetime.now(timezone.utc)
                }
            }
        )

        flash("Cadastro atualizado com sucesso!", "success")

    except Exception:
        current_app.logger.exception("Erro ao editar cliente.")
        flash("Não foi possível atualizar o cadastro.", "danger")

    return redirect(url_for("clientes.listar_clientes"))


@clientes_bp.route("/clientes/<cliente_id>/excluir", methods=["POST"])
def excluir_cliente(cliente_id):
    cliente = buscar_cliente(cliente_id)

    if not cliente:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("clientes.listar_clientes"))

    try:
        db = get_database()

        db["clientes"].delete_one({
            "_id": ObjectId(cliente_id),
            "usuario_id": obter_usuario_id()
        })

        flash("Cliente excluído com sucesso.", "success")

    except Exception:
        current_app.logger.exception("Erro ao excluir cliente.")
        flash("Não foi possível excluir o cliente.", "danger")

    return redirect(url_for("clientes.listar_clientes"))