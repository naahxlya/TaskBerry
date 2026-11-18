from datetime import datetime, timezone, timedelta
import math
import re

from bson import ObjectId
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from app.database.connection import get_database

clientes_bp = Blueprint("clientes", __name__)
ITENS_POR_PAGINA = 25
PRAZO_DIAS = 10


def agora():
    return datetime.now(timezone.utc)


def obter_usuario_id():
    return session.get("usuario_id")


def filtro_usuario():
    return {"usuario_id": obter_usuario_id()}


def buscar_cliente(cliente_id):
    if not ObjectId.is_valid(cliente_id):
        return None
    return get_database()["clientes"].find_one({"_id": ObjectId(cliente_id), **filtro_usuario()})


def processar_prazos(colecao):
    """Move arquivados vencidos para a lixeira e elimina lixeiras vencidas."""
    momento = agora()
    limite_arquivo = momento - timedelta(days=PRAZO_DIAS)
    limite_lixeira = momento - timedelta(days=PRAZO_DIAS)
    base_filtro = filtro_usuario()

    colecao.update_many(
        {**base_filtro, "arquivado": True, "excluido": {"$ne": True},
         "arquivado_em": {"$lte": limite_arquivo}},
        {"$set": {"excluido": True, "excluido_em": momento, "atualizado_em": momento}}
    )
    colecao.delete_many(
        {**base_filtro, "excluido": True, "excluido_em": {"$lte": limite_lixeira}}
    )


def filtro_busca(busca):
    filtro = filtro_usuario()
    if busca:
        termo = re.escape(busca)
        filtro["$or"] = [
            {"nome": {"$regex": termo, "$options": "i"}},
            {"telefone": {"$regex": termo, "$options": "i"}},
            {"email": {"$regex": termo, "$options": "i"}}
        ]
    return filtro


@clientes_bp.route("/clientes")
def listar_clientes():
    db = get_database()
    colecao = db["clientes"]
    processar_prazos(colecao)

    busca = request.args.get("busca", "").strip()
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1

    filtro = {**filtro_busca(busca), "arquivado": {"$ne": True}, "excluido": {"$ne": True}}
    total_filtrado = colecao.count_documents(filtro)
    total_paginas = max(1, math.ceil(total_filtrado / ITENS_POR_PAGINA))
    pagina = min(pagina, total_paginas)
    deslocamento = (pagina - 1) * ITENS_POR_PAGINA

    configuracao = db["configuracoes"].find_one(
        {"usuario_id": session.get("usuario_id")}, {"preferencias.ordem_clientes": 1}
    ) or {}
    ordem_clientes = configuracao.get("preferencias", {}).get("ordem_clientes", "nome_asc")
    ordenacao = {
        "nome_asc": [("nome", 1), ("_id", 1)],
        "atualizado_desc": [("atualizado_em", -1), ("_id", -1)],
        "atualizado_asc": [("atualizado_em", 1), ("_id", 1)]
    }.get(ordem_clientes, [("nome", 1), ("_id", 1)])
    clientes = list(colecao.find(filtro).sort(ordenacao).skip(deslocamento).limit(ITENS_POR_PAGINA))
    total_clientes = colecao.count_documents({**filtro_usuario(), "arquivado": {"$ne": True}, "excluido": {"$ne": True}})
    arquivados = list(colecao.find({**filtro_usuario(), "arquivado": True, "excluido": {"$ne": True}}).sort("arquivado_em", -1).limit(100))
    lixeira = list(colecao.find({**filtro_usuario(), "excluido": True}).sort("excluido_em", -1).limit(100))

    return render_template(
        "clientes.html", clientes=clientes, busca=busca, total_clientes=total_clientes,
        total_filtrado=total_filtrado, pagina=pagina, total_paginas=total_paginas,
        primeira_linha=deslocamento + 1 if total_filtrado else 0,
        ultima_linha=min(deslocamento + ITENS_POR_PAGINA, total_filtrado),
        arquivados=arquivados, lixeira=lixeira,
        agora=agora(), prazo_dias=PRAZO_DIAS, ordem_clientes=ordem_clientes
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

    colecao = get_database()["clientes"]
    if email and colecao.find_one({**filtro_usuario(), "email": email, "arquivado": {"$ne": True}, "excluido": {"$ne": True}}):
        flash("Este e-mail já está cadastrado em um cliente ativo.", "warning")
        return redirect(url_for("clientes.listar_clientes"))
    momento = agora()
    try:
        colecao.insert_one({
            **filtro_usuario(), "nome": nome, "telefone": telefone, "email": email,
            "endereco": endereco, "observacoes": observacoes, "total_servicos": 0,
            "arquivado": False, "excluido": False,
            "criado_em": momento, "atualizado_em": momento
        })
        flash("Cliente cadastrado com sucesso!", "success")
    except Exception:
        current_app.logger.exception("Erro ao cadastrar cliente.")
        flash("Não foi possível cadastrar o cliente.", "danger")
    return redirect(url_for("clientes.listar_clientes"))


@clientes_bp.route("/clientes/<cliente_id>/editar", methods=["POST"])
def editar_cliente(cliente_id):
    cliente = buscar_cliente(cliente_id)
    if not cliente or cliente.get("arquivado") or cliente.get("excluido"):
        flash("Cliente não encontrado ou indisponível para edição.", "danger")
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
    colecao = get_database()["clientes"]
    if email and colecao.find_one({**filtro_usuario(), "email": email, "_id": {"$ne": ObjectId(cliente_id)}, "arquivado": {"$ne": True}, "excluido": {"$ne": True}}):
        flash("Este e-mail já pertence a outro cliente ativo.", "warning")
        return redirect(url_for("clientes.listar_clientes"))
    try:
        colecao.update_one({"_id": ObjectId(cliente_id), **filtro_usuario()}, {"$set": {
            "nome": nome, "telefone": telefone, "email": email, "endereco": endereco,
            "observacoes": observacoes, "atualizado_em": agora()
        }})
        flash("Cadastro atualizado com sucesso!", "success")
    except Exception:
        current_app.logger.exception("Erro ao editar cliente.")
        flash("Não foi possível atualizar o cadastro.", "danger")
    return redirect(url_for("clientes.listar_clientes"))


@clientes_bp.route("/clientes/<cliente_id>/arquivar", methods=["POST"])
def arquivar_cliente(cliente_id):
    cliente = buscar_cliente(cliente_id)
    if not cliente or cliente.get("arquivado") or cliente.get("excluido"):
        flash("Cliente não encontrado ou já arquivado.", "warning")
        return redirect(url_for("clientes.listar_clientes"))
    momento = agora()
    get_database()["clientes"].update_one({"_id": ObjectId(cliente_id), **filtro_usuario()}, {"$set": {
        "arquivado": True, "arquivado_em": momento, "atualizado_em": momento
    }})
    flash("Cliente arquivado. Ele ficará disponível para restauração por 10 dias.", "success")
    return redirect(url_for("clientes.listar_clientes"))


@clientes_bp.route("/clientes/<cliente_id>/restaurar", methods=["POST"])
def restaurar_cliente(cliente_id):
    cliente = buscar_cliente(cliente_id)
    if not cliente:
        flash("Cliente não encontrado.", "danger")
        return redirect(url_for("clientes.listar_clientes"))
    if cliente.get("excluido"):
        # A restauração da lixeira devolve o registro à área de arquivados.
        atualizacao = {"excluido": False, "excluido_em": None, "arquivado": True, "arquivado_em": agora()}
        mensagem = "Cliente restaurado para Arquivados."
    elif cliente.get("arquivado"):
        atualizacao = {"arquivado": False, "arquivado_em": None}
        mensagem = "Cliente restaurado para o painel de clientes."
    else:
        flash("Este cliente já está ativo.", "info")
        return redirect(url_for("clientes.listar_clientes"))
    atualizacao["atualizado_em"] = agora()
    get_database()["clientes"].update_one({"_id": ObjectId(cliente_id), **filtro_usuario()}, {"$set": atualizacao})
    flash(mensagem, "success")
    return redirect(url_for("clientes.listar_clientes"))


@clientes_bp.route("/clientes/<cliente_id>/excluir-permanentemente", methods=["POST"])
def excluir_permanentemente(cliente_id):
    cliente = buscar_cliente(cliente_id)
    if not cliente or not cliente.get("excluido"):
        flash("Somente clientes que estão na lixeira podem ser excluídos permanentemente.", "warning")
        return redirect(url_for("clientes.listar_clientes"))
    try:
        get_database()["clientes"].delete_one({"_id": ObjectId(cliente_id), **filtro_usuario(), "excluido": True})
        flash("Cliente removido permanentemente.", "success")
    except Exception:
        current_app.logger.exception("Erro ao excluir cliente permanentemente.")
        flash("Não foi possível excluir o cliente.", "danger")
    return redirect(url_for("clientes.listar_clientes"))

@clientes_bp.route("/clientes/<cliente_id>/excluir", methods=["POST"])
def excluir_cliente(cliente_id):
    """Envia um cliente ativo para a lixeira."""
    cliente = buscar_cliente(cliente_id)
    if not cliente or cliente.get("arquivado") or cliente.get("excluido"):
        flash("Cliente não encontrado ou indisponível para exclusão.", "warning")
        return redirect(url_for("clientes.listar_clientes"))

    try:
        momento = agora()
        resultado = get_database()["clientes"].update_one(
            {
                "_id": ObjectId(cliente_id),
                **filtro_usuario(),
                "arquivado": {"$ne": True},
                "excluido": {"$ne": True}
            },
            {
                "$set": {
                    "excluido": True,
                    "excluido_em": momento,
                    "atualizado_em": momento
                }
            }
        )

        if resultado.modified_count:
            flash("Cliente enviado para a lixeira com sucesso!", "success")
        else:
            flash("Não foi possível localizar o cliente para envio à lixeira.", "warning")
    except Exception:
        current_app.logger.exception("Erro ao enviar cliente para a lixeira.")
        flash("Não foi possível enviar o cliente para a lixeira.", "danger")

    return redirect(url_for("clientes.listar_clientes"))