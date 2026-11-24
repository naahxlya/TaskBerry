from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4
import re

from bson import ObjectId
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, current_app
)

from app.database.connection import get_database
from app.services.financeiro_service import registrar_despesa_aquisicao_ferramenta, registrar_despesa_manutencao_ferramenta


ferramentas_bp = Blueprint("ferramentas", __name__)


# =====================================================
# FUNÇÕES AUXILIARES
# =====================================================

def agora():
    return datetime.now(timezone.utc)


def usuario_id():
    return session.get("usuario_id")


def voltar():
    return redirect(url_for("ferramentas.listar_ferramentas"))


def converter_data(valor, obrigatoria=False):
    valor = (valor or "").strip()

    if not valor:
        if obrigatoria:
            raise ValueError("Informe uma data.")
        return None

    try:
        return datetime.strptime(valor, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        raise ValueError("Data inválida.")


def validar_data_historica(data, descricao="registro"):
    if data and data.date() < (agora().date() - timedelta(days=365)):
        raise ValueError(f"A data de {descricao} deve estar dentro dos últimos 12 meses.")
    return data


def converter_valor(valor):
    valor = (valor or "").strip()

    if not valor:
        return 0.0

    valor = valor.replace("R$", "").replace(" ", "")

    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")

    try:
        numero = Decimal(valor)
    except InvalidOperation:
        raise ValueError("Valor inválido.")

    if numero < 0:
        raise ValueError("O valor não pode ser negativo.")

    return float(numero.quantize(Decimal("0.01")))


def filtro_usuario():
    return {
        "usuario_id": usuario_id(),
        "arquivada": {"$ne": True},
        "excluida": {"$ne": True}
    }


def buscar_ferramenta(ferramenta_id):
    if not ObjectId.is_valid(ferramenta_id):
        return None

    return get_database()["ferramentas"].find_one({
        "_id": ObjectId(ferramenta_id),
        **filtro_usuario()
    })


def gerar_codigo():
    return f"FER-{str(ObjectId())[-6:].upper()}"


def preparar_ferramenta(item):
    item.setdefault("codigo", "Sem código")
    item.setdefault("categoria", "Outros")
    item.setdefault("marca", "")
    item.setdefault("modelo", "")
    item.setdefault("numero_serie", "")
    item.setdefault("situacao", "disponivel")
    item.setdefault("historico_manutencao", [])
    item.setdefault("valor_aquisicao", 0)

    historico = item["historico_manutencao"]

    item["total_manutencoes"] = len(historico)

    item["manutencao_aberta"] = next(
        (
            registro for registro in reversed(historico)
            if registro.get("situacao") == "em_andamento"
        ),
        None
    )

    return item


# =====================================================
# LISTAGEM
# =====================================================

@ferramentas_bp.route("/ferramentas")
def listar_ferramentas():

    if not usuario_id():
        return redirect(url_for("inicio"))

    db = get_database()
    colecao = db["ferramentas"]

    busca = request.args.get("busca", "").strip()
    categoria = request.args.get("categoria", "").strip()
    situacao = request.args.get("situacao", "").strip()

    filtro = {**filtro_usuario(), "arquivada": {"$ne": True}}

    if busca:
        termo = re.escape(busca)

        filtro["$or"] = [
            {"nome": {"$regex": termo, "$options": "i"}},
            {"codigo": {"$regex": termo, "$options": "i"}},
            {"marca": {"$regex": termo, "$options": "i"}},
            {"modelo": {"$regex": termo, "$options": "i"}},
            {"numero_serie": {"$regex": termo, "$options": "i"}}
        ]

    if categoria:
        filtro["categoria"] = categoria

    if situacao:
        filtro["situacao"] = situacao

    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total_registros = colecao.count_documents(filtro)
    total_paginas = max(1, (total_registros + 9) // 10)
    pagina = min(pagina, total_paginas)
    ferramentas = [
        preparar_ferramenta(item)
        for item in colecao.find(filtro).sort("criado_em", -1).skip((pagina - 1) * 10).limit(10)
    ]

    todas = list(colecao.find({**filtro_usuario(), "arquivada": {"$ne": True}, "excluida": {"$ne": True}}))

    total_ferramentas = len(todas)

    total_disponiveis = sum(
        item.get("situacao", "disponivel") == "disponivel"
        for item in todas
    )

    total_em_uso = sum(
        item.get("situacao") == "em_uso"
        for item in todas
    )

    total_manutencao = sum(
        item.get("situacao") == "manutencao"
        for item in todas
    )

    total_baixadas = sum(
        item.get("situacao") == "baixada"
        for item in todas
    )

    valor_aquisicao_total = round(
        sum(float(item.get("valor_aquisicao") or 0) for item in todas),
        2
    )

    categorias = sorted({
        item.get("categoria")
        for item in todas
        if item.get("categoria")
    })

    acompanhamentos = []

    for ferramenta in todas:
        for registro in ferramenta.get("historico_manutencao", []):
            acompanhamentos.append({
                "ferramenta_id": ferramenta["_id"],
                "ferramenta_nome": ferramenta.get("nome", ""),
                "codigo": ferramenta.get("codigo", ""),
                "marca": ferramenta.get("marca", ""),
                "modelo": ferramenta.get("modelo", ""),
                **registro
            })

    acompanhamentos.sort(
        key=lambda registro: (
            registro.get("data_envio") or datetime.min.replace(
                tzinfo=timezone.utc
            )
        ),
        reverse=True
    )

    manutencoes_abertas = [
        registro for registro in acompanhamentos
        if registro.get("situacao") == "em_andamento"
    ]

    historico_recente = acompanhamentos[:8]

    return render_template(
        "ferramentas.html",
        ferramentas=ferramentas,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        busca=busca,
        categoria_selecionada=categoria,
        situacao_selecionada=situacao,
        categorias=categorias,
        total_ferramentas=total_ferramentas,
        total_disponiveis=total_disponiveis,
        total_em_uso=total_em_uso,
        total_manutencao=total_manutencao,
        total_baixadas=total_baixadas,
        valor_aquisicao_total=valor_aquisicao_total,
        acompanhamentos=acompanhamentos,
        manutencoes_abertas=manutencoes_abertas,
        historico_recente=historico_recente
    )


# =====================================================
# CADASTRO
# =====================================================

@ferramentas_bp.route("/ferramentas/novo", methods=["POST"])
def cadastrar_ferramenta():

    if not usuario_id():
        return redirect(url_for("inicio"))

    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()

    if not nome or not categoria:
        flash("Nome e categoria são obrigatórios.", "danger")
        return voltar()

    try:
        data_aquisicao = validar_data_historica(
            converter_data(request.form.get("data_aquisicao")),
            "aquisição"
        )
        valor_aquisicao = converter_valor(
            request.form.get("valor_aquisicao")
        )
    except ValueError as erro:
        flash(str(erro), "danger")
        return voltar()

    codigo = gerar_codigo()
    data_criacao = agora()
    fornecedor = request.form.get("fornecedor", "").strip()
    compra_antiga = request.form.get("compra_antiga") == "1"

    ferramenta = {
        "usuario_id": usuario_id(),
        "codigo": codigo,
        "nome": nome,
        "categoria": categoria,
        "marca": request.form.get("marca", "").strip(),
        "modelo": request.form.get("modelo", "").strip(),
        "numero_serie": request.form.get("numero_serie", "").strip(),
        "descricao": request.form.get("descricao", "").strip(),

        "aquisicao": {
            "data": data_aquisicao,
            "valor": valor_aquisicao,
            "fornecedor": fornecedor,
            "integrado_erp": False,
            "compra_antiga": compra_antiga
        },

        "compra_antiga": compra_antiga,
        "data_aquisicao": data_aquisicao,
        "valor_aquisicao": valor_aquisicao,
        "fornecedor": fornecedor,

        "localizacao": request.form.get("localizacao", "").strip(),
        "observacoes": request.form.get("observacoes", "").strip(),

        "situacao": "disponivel",
        "chamado_atual_id": None,
        "historico_manutencao": [],

        "arquivada": False,
        "criado_em": data_criacao,
        "atualizado_em": data_criacao
    }

    try:
        db = get_database()
        resultado = db["ferramentas"].insert_one(ferramenta)
        ferramenta["_id"] = resultado.inserted_id

        if valor_aquisicao > 0 and not compra_antiga:
            try:
                registrar_despesa_aquisicao_ferramenta(
                    db,
                    usuario_id(),
                    ferramenta
                )
            except Exception:
                current_app.logger.exception(
                    "Ferramenta cadastrada, mas a aquisição não foi integrada ao Financeiro."
                )
                flash(
                    "A ferramenta foi cadastrada, mas houve falha ao integrar a aquisição ao Financeiro.",
                    "warning"
                )

        flash(
            f"{nome} cadastrado com sucesso! Código: {codigo}",
            "success"
        )

    except Exception:
        current_app.logger.exception("Erro ao cadastrar ferramenta.")
        flash("Não foi possível cadastrar a ferramenta.", "danger")

    return voltar()


# =====================================================
# EDIÇÃO
# =====================================================

@ferramentas_bp.route(
    "/ferramentas/<ferramenta_id>/editar",
    methods=["POST"]
)
def editar_ferramenta(ferramenta_id):

    ferramenta = buscar_ferramenta(ferramenta_id)

    if not ferramenta:
        flash("Ferramenta não encontrada.", "danger")
        return voltar()

    if ferramenta.get("situacao") in ("em_uso", "manutencao"):
        flash(
            "Não é possível editar os dados principais enquanto "
            "o equipamento estiver em uso ou em manutenção.",
            "warning"
        )
        return voltar()

    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()

    if not nome or not categoria:
        flash("Nome e categoria são obrigatórios.", "danger")
        return voltar()

    try:
        data_aquisicao = converter_data(
            request.form.get("data_aquisicao")
        )
        valor_aquisicao = converter_valor(
            request.form.get("valor_aquisicao")
        )
    except ValueError as erro:
        flash(str(erro), "danger")
        return voltar()

    fornecedor = request.form.get("fornecedor", "").strip()

    dados = {
        "nome": nome,
        "categoria": categoria,
        "marca": request.form.get("marca", "").strip(),
        "modelo": request.form.get("modelo", "").strip(),
        "numero_serie": request.form.get("numero_serie", "").strip(),
        "descricao": request.form.get("descricao", "").strip(),
        "data_aquisicao": data_aquisicao,
        "valor_aquisicao": valor_aquisicao,
        "fornecedor": fornecedor,
        "aquisicao.data": data_aquisicao,
        "aquisicao.valor": valor_aquisicao,
        "aquisicao.fornecedor": fornecedor,
        "localizacao": request.form.get("localizacao", "").strip(),
        "observacoes": request.form.get("observacoes", "").strip(),
        "atualizado_em": agora()
    }

    try:
        get_database()["ferramentas"].update_one(
            {
                "_id": ObjectId(ferramenta_id),
                **filtro_usuario()
            },
            {"$set": dados}
        )

        flash("Ferramenta atualizada com sucesso!", "success")

    except Exception:
        current_app.logger.exception("Erro ao editar ferramenta.")
        flash("Não foi possível atualizar a ferramenta.", "danger")

    return voltar()


# =====================================================
# ENVIAR PARA MANUTENÇÃO
# =====================================================

@ferramentas_bp.route(
    "/ferramentas/<ferramenta_id>/manutencao",
    methods=["POST"]
)
def enviar_para_manutencao(ferramenta_id):

    ferramenta = buscar_ferramenta(ferramenta_id)

    if not ferramenta:
        flash("Ferramenta não encontrada.", "danger")
        return voltar()

    if ferramenta.get("situacao", "disponivel") != "disponivel":
        flash(
            "Somente equipamentos disponíveis podem ser enviados "
            "para manutenção.",
            "warning"
        )
        return voltar()

    try:
        data_envio = validar_data_historica(
            converter_data(request.form.get("data_envio"), obrigatoria=True),
            "envio para manutenção"
        )
        valor_estimado = converter_valor(
            request.form.get("valor_estimado")
        )
    except ValueError as erro:
        flash(str(erro), "danger")
        return voltar()

    registro = {
        "manutencao_id": str(uuid4()),
        "data_envio": data_envio,
        "data_conclusao": None,
        "valor_estimado": valor_estimado,
        "valor_final": None,
        "profissional": request.form.get("profissional", "").strip(),
        "descricao": request.form.get("descricao_manutencao", "").strip(),
        "situacao": "em_andamento",
        "integrado_erp": False,
        "criado_em": agora()
    }

    try:
        resultado = get_database()["ferramentas"].update_one(
            {
                "_id": ObjectId(ferramenta_id),
                **filtro_usuario(),
                "situacao": "disponivel"
            },
            {
                "$push": {"historico_manutencao": registro},
                "$set": {
                    "situacao": "manutencao",
                    "atualizado_em": agora()
                }
            }
        )

        if resultado.modified_count:
            try:
                registrar_despesa_manutencao_ferramenta(
                    get_database(),
                    usuario_id(),
                    ferramenta,
                    registro
                )
            except Exception:
                current_app.logger.exception(
                    "Manutenção registrada, mas a previsão não foi integrada ao Financeiro."
                )
                flash(
                    "A manutenção foi registrada, mas houve falha ao integrar a previsão ao Financeiro.",
                    "warning"
                )
            flash("Manutenção registrada com sucesso.", "success")
        else:
            flash(
                "A situação do equipamento mudou. Atualize a página.",
                "warning"
            )

    except Exception:
        current_app.logger.exception("Erro ao registrar manutenção.")
        flash("Não foi possível registrar a manutenção.", "danger")

    return voltar()


# =====================================================
# CONFIRMAR REPARO
# =====================================================

@ferramentas_bp.route(
    "/ferramentas/<ferramenta_id>/confirmar-reparo",
    methods=["POST"]
)
def confirmar_reparo(ferramenta_id):

    ferramenta = buscar_ferramenta(ferramenta_id)

    if not ferramenta or ferramenta.get("situacao") != "manutencao":
        flash("Não há manutenção em aberto para este equipamento.", "warning")
        return voltar()

    registro = next(
        (
            item for item in reversed(
                ferramenta.get("historico_manutencao", [])
            )
            if item.get("situacao") == "em_andamento"
        ),
        None
    )

    if not registro:
        flash("Registro de manutenção em aberto não encontrado.", "danger")
        return voltar()

    try:
        data_conclusao = converter_data(
            request.form.get("data_conclusao"),
            obrigatoria=True
        )

        valor_digitado = request.form.get("valor_final", "").strip()

        if valor_digitado:
            valor_final = converter_valor(valor_digitado)
        else:
            valor_final = float(registro.get("valor_estimado") or 0)

    except ValueError as erro:
        flash(str(erro), "danger")
        return voltar()

    try:
        resultado = get_database()["ferramentas"].update_one(
            {
                "_id": ObjectId(ferramenta_id),
                **filtro_usuario(),
                "situacao": "manutencao",
                "historico_manutencao.manutencao_id": registro["manutencao_id"]
            },
            {
                "$set": {
                    "historico_manutencao.$.situacao": "concluida",
                    "historico_manutencao.$.data_conclusao": data_conclusao,
                    "historico_manutencao.$.valor_final": valor_final,
                    "situacao": "disponivel",
                    "atualizado_em": agora()
                }
            }
        )

        if resultado.modified_count:
            try:
                manutencao_atualizada = dict(registro)
                manutencao_atualizada.update({
                    "valor_final": valor_final,
                    "situacao": "concluida",
                    "data_conclusao": data_conclusao
                })
                registrar_despesa_manutencao_ferramenta(
                    get_database(),
                    usuario_id(),
                    ferramenta,
                    manutencao_atualizada,
                    valor=valor_final,
                    data_movimento=data_conclusao
                )
                get_database()["ferramentas"].update_one(
                    {
                        "_id": ferramenta["_id"],
                        **filtro_usuario(),
                        "historico_manutencao.manutencao_id": registro["manutencao_id"]
                    },
                    {"$set": {"historico_manutencao.$.integrado_erp": True}}
                )
            except Exception:
                current_app.logger.exception(
                    "Reparo confirmado, mas houve falha ao atualizar a despesa no Financeiro."
                )
                flash(
                    "O reparo foi confirmado, mas a despesa não foi atualizada no Financeiro.",
                    "warning"
                )
            flash(
                "Reparo confirmado. Equipamento disponível novamente!",
                "success"
            )
        else:
            flash("Não foi possível confirmar o reparo.", "warning")

    except Exception:
        current_app.logger.exception("Erro ao confirmar reparo.")
        flash("Ocorreu um erro ao confirmar o reparo.", "danger")

    return voltar()


@ferramentas_bp.route("/ferramentas/arquivadas")
def ferramentas_arquivadas():
    db = get_database()
    busca = request.args.get("busca", "").strip()
    filtro = {**filtro_usuario(), "arquivada": True, "excluida": {"$ne": True}}
    if busca:
        termo = re.escape(busca)
        filtro["$or"] = [{"nome": {"$regex": termo, "$options": "i"}}, {"codigo": {"$regex": termo, "$options": "i"}}]
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total = db["ferramentas"].count_documents(filtro)
    paginas = max(1, (total + 24) // 25)
    pagina = min(pagina, paginas)
    itens = [preparar_ferramenta(x) for x in db["ferramentas"].find(filtro).sort("arquivada_em", -1).skip((pagina-1)*25).limit(25)]
    return render_template("registros_especiais.html", modulo="Ferramentas", tipo="arquivados", itens=itens, total=total, pagina=pagina, total_paginas=paginas, busca=busca, voltar=url_for("ferramentas.listar_ferramentas"), restaurar_endpoint="ferramentas.restaurar_ferramenta", excluir_endpoint=None, campo_data="arquivada_em", nome_campo="nome", detalhe_campo="codigo", rota_lista="ferramentas.listar_ferramentas")


@ferramentas_bp.route("/ferramentas/<ferramenta_id>/restaurar", methods=["POST"])
def restaurar_ferramenta(ferramenta_id):
    if not ObjectId.is_valid(ferramenta_id):
        flash("Equipamento não encontrado.", "danger")
        return redirect(url_for("ferramentas.ferramentas_arquivadas"))
    resultado = get_database()["ferramentas"].update_one(
        {"_id": ObjectId(ferramenta_id), **filtro_usuario(), "arquivada": True},
        {"$set": {"arquivada": False, "atualizado_em": agora()}, "$unset": {"arquivada_em": ""}}
    )
    flash("Equipamento restaurado para a lista de ferramentas." if resultado.modified_count else "Não foi possível restaurar o equipamento.", "success" if resultado.modified_count else "warning")
    return redirect(url_for("ferramentas.ferramentas_arquivadas"))


@ferramentas_bp.route("/ferramentas/<ferramenta_id>/excluir", methods=["POST"])
def enviar_ferramenta_lixeira(ferramenta_id):
    ferramenta = buscar_ferramenta(ferramenta_id)
    if not ferramenta:
        flash("Ferramenta não encontrada.", "danger")
        return voltar()
    if ferramenta.get("situacao") in ("em_uso", "manutencao"):
        flash("Não é possível excluir uma ferramenta em uso ou em manutenção.", "warning")
        return voltar()
    momento = agora()
    get_database()["ferramentas"].update_one(
        {"_id": ferramenta["_id"], **filtro_usuario()},
        {"$set": {"excluida": True, "excluida_em": momento, "atualizado_em": momento}}
    )
    flash("Ferramenta enviada à lixeira. O histórico foi preservado.", "success")
    return voltar()


@ferramentas_bp.route("/ferramentas/lixeira")
def ferramentas_lixeira():
    db = get_database()
    colecao = db["ferramentas"]
    busca = request.args.get("busca", "").strip()
    filtro = {"usuario_id": usuario_id(), "excluida": True}
    if busca:
        termo = re.escape(busca)
        filtro["$or"] = [{"nome": {"$regex": termo, "$options": "i"}}, {"codigo": {"$regex": termo, "$options": "i"}}]
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total = colecao.count_documents(filtro)
    paginas = max(1, (total + 24) // 25)
    pagina = min(pagina, paginas)
    itens = [preparar_ferramenta(x) for x in colecao.find(filtro).sort("excluida_em", -1).skip((pagina-1)*25).limit(25)]
    return render_template("registros_especiais.html", modulo="Ferramentas", tipo="lixeira", itens=itens, total=total, pagina=pagina, total_paginas=paginas, busca=busca, voltar=url_for("ferramentas.listar_ferramentas"), restaurar_endpoint="ferramentas.restaurar_ferramenta", excluir_endpoint="ferramentas.excluir_ferramenta_permanentemente", campo_data="excluida_em", nome_campo="nome", detalhe_campo="codigo", rota_lista="ferramentas.listar_ferramentas")


@ferramentas_bp.route("/ferramentas/<ferramenta_id>/restaurar-lixeira", methods=["POST"])
def restaurar_ferramenta_lixeira(ferramenta_id):
    if not ObjectId.is_valid(ferramenta_id):
        flash("Ferramenta não encontrada.", "danger")
        return redirect(url_for("ferramentas.ferramentas_lixeira"))
    resultado = get_database()["ferramentas"].update_one(
        {"_id": ObjectId(ferramenta_id), "usuario_id": usuario_id(), "excluida": True},
        {"$set": {"excluida": False, "atualizado_em": agora()}, "$unset": {"excluida_em": ""}}
    )
    flash("Ferramenta restaurada." if resultado.modified_count else "Não foi possível restaurar a ferramenta.", "success" if resultado.modified_count else "warning")
    return redirect(url_for("ferramentas.ferramentas_lixeira"))


@ferramentas_bp.route("/ferramentas/<ferramenta_id>/excluir-permanentemente", methods=["POST"])
def excluir_ferramenta_permanentemente(ferramenta_id):
    if not ObjectId.is_valid(ferramenta_id):
        return redirect(url_for("ferramentas.ferramentas_lixeira"))
    resultado = get_database()["ferramentas"].delete_one({"_id": ObjectId(ferramenta_id), "usuario_id": usuario_id(), "excluida": True})
    flash("Ferramenta excluída permanentemente." if resultado.deleted_count else "Não foi possível excluir a ferramenta.", "success" if resultado.deleted_count else "warning")
    return redirect(url_for("ferramentas.ferramentas_lixeira"))


# =====================================================
# ARQUIVAR
# =====================================================

@ferramentas_bp.route(
    "/ferramentas/<ferramenta_id>/arquivar",
    methods=["POST"]
)
def arquivar_ferramenta(ferramenta_id):

    ferramenta = buscar_ferramenta(ferramenta_id)

    if not ferramenta:
        flash("Ferramenta não encontrada.", "danger")
        return voltar()

    if ferramenta.get("situacao") in ("em_uso", "manutencao"):
        flash(
            "Não é possível arquivar um equipamento em uso "
            "ou em manutenção.",
            "warning"
        )
        return voltar()

    try:
        get_database()["ferramentas"].update_one(
            {
                "_id": ObjectId(ferramenta_id),
                **filtro_usuario()
            },
            {
                "$set": {
                    "arquivada": True,
                    "arquivada_em": agora(),
                    "atualizado_em": agora()
                }
            }
        )

        flash(
            "Equipamento arquivado. O histórico foi preservado.",
            "success"
        )

    except Exception:
        current_app.logger.exception("Erro ao arquivar ferramenta.")
        flash("Não foi possível arquivar o equipamento.", "danger")

    return voltar()