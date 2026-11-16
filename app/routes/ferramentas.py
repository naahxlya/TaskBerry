from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4
import re

from bson import ObjectId
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, flash, current_app
)

from app.database.connection import get_database


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
        "arquivada": {"$ne": True}
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

    filtro = filtro_usuario()

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

    ferramentas = [
        preparar_ferramenta(item)
        for item in colecao.find(filtro).sort("criado_em", -1)
    ]

    todas = list(colecao.find(filtro_usuario()))

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
        data_aquisicao = converter_data(
            request.form.get("data_aquisicao")
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
            "integrado_erp": False
        },

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
        get_database()["ferramentas"].insert_one(ferramenta)

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
        data_envio = converter_data(
            request.form.get("data_envio"),
            obrigatoria=True
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