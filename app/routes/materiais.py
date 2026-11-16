from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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


materiais_bp = Blueprint("materiais", __name__)

PERCENTUAIS_VALIDOS = set(range(0, 101, 10))


def obter_usuario_id():
    return session.get("usuario_id")


def agora_utc():
    return datetime.now(timezone.utc)


def converter_numero(valor, permitir_zero=True):
    texto = str(valor or "").strip().replace("R$", "").replace(" ", "")

    if not texto:
        raise InvalidOperation

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    numero = Decimal(texto)

    if not numero.is_finite():
        raise InvalidOperation

    if numero < 0 or (not permitir_zero and numero == 0):
        raise InvalidOperation

    return float(numero)


def converter_inteiro(valor, minimo=0):
    numero = int(str(valor or "").strip())

    if numero < minimo:
        raise ValueError

    return numero


def converter_data(valor):
    if not valor:
        return None

    return datetime.strptime(valor, "%Y-%m-%d")


def buscar_material(material_id, incluir_arquivados=False):
    if not ObjectId.is_valid(material_id):
        return None

    filtro = {
        "_id": ObjectId(material_id),
        "usuario_id": obter_usuario_id()
    }

    if not incluir_arquivados:
        filtro["arquivado"] = {"$ne": True}

    return get_database()["materiais"].find_one(filtro)


def registrar_movimentacao(
    db,
    material,
    tipo,
    quantidade,
    descricao,
    dados_adicionais=None
):
    registro = {
        "usuario_id": obter_usuario_id(),
        "material_id": material["_id"],
        "material_nome": material["nome"],
        "tipo": tipo,
        "quantidade": quantidade,
        "descricao": descricao,
        "data": agora_utc(),
        "responsavel": session.get("usuario_nome", "Usuário")
    }

    if dados_adicionais:
        registro.update(dados_adicionais)

    db["movimentacoes_estoque"].insert_one(registro)


# =====================================================
# CÁLCULO E CONVERSÃO DO ESTOQUE
# =====================================================

def calcular_saldo(quantidade_fechada, percentual_aberto):
    """
    Calcula o saldo equivalente.

    quantidade_fechada:
        Quantidade de unidades inteiras e fechadas.

    percentual_aberto:
        Percentual restante de uma unidade que já foi aberta.
        Zero significa que não existe unidade aberta.
    """

    saldo = quantidade_fechada + (percentual_aberto / 100)

    return round(max(saldo, 0), 2)


def converter_estoque_do_formulario(quantidade_unidades, percentual):
    """
    Converte os valores apresentados no formulário para o formato
    interno já utilizado pelo banco de dados.

    Na interface:
        5 unidades e 100% = 5 unidades inteiras.
        5 unidades e 75% = 4 inteiras e uma aberta com 75%.
        5 unidades e 50% = 4 inteiras e uma aberta com 50%.

    No banco:
        Unidades fechadas e percentual da unidade aberta são
        armazenados separadamente.
    """

    if quantidade_unidades <= 0:
        return 0, 0

    if percentual >= 100:
        return quantidade_unidades, 0

    return quantidade_unidades - 1, percentual


def formatar_material(material):
    quantidade_fechada = material.get("quantidade_fechada", 0)
    percentual_aberto = material.get("percentual_aberto", 0)

    material["saldo_equivalente"] = calcular_saldo(
        quantidade_fechada,
        percentual_aberto
    )

    # Quantidade total apresentada ao usuário.
    material["quantidade_unidades"] = (
        quantidade_fechada + (1 if percentual_aberto > 0 else 0)
    )

    # Percentual apresentado no formulário.
    # Quando não há unidade aberta, todas estão inteiras.
    material["percentual_formulario"] = (
        percentual_aberto if percentual_aberto > 0
        else 100 if quantidade_fechada > 0
        else 0
    )

    material["percentual_visual"] = (
        percentual_aberto if percentual_aberto > 0
        else 100 if quantidade_fechada > 0
        else 0
    )

    capacidade = material.get("capacidade_por_unidade", 0)

    material["quantidade_total"] = round(
        material["saldo_equivalente"] * capacidade,
        2
    ) if capacidade else material["saldo_equivalente"]

    material["valor_estoque"] = round(
        material["saldo_equivalente"] *
        material.get("valor_unitario", 0),
        2
    )

    material["estoque_baixo"] = (
        material["saldo_equivalente"]
        <= material.get("estoque_minimo", 0)
    )

    return material


def voltar_para_lista():
    return redirect(url_for("materiais.listar_materiais"))


def validar_percentual(valor):
    percentual = converter_inteiro(valor)

    if percentual not in PERCENTUAIS_VALIDOS:
        raise ValueError

    return percentual


# =====================================================
# LISTAGEM DE MATERIAIS
# =====================================================

@materiais_bp.route("/materiais")
def listar_materiais():
    usuario_id = obter_usuario_id()

    if not usuario_id:
        return redirect(url_for("inicio"))

    db = get_database()
    colecao = db["materiais"]

    busca = request.args.get("busca", "").strip()
    categoria = request.args.get("categoria", "").strip()
    filtro_estoque = request.args.get("estoque", "").strip()

    filtro = {
        "usuario_id": usuario_id,
        "arquivado": {"$ne": True}
    }

    if busca:
        termo = re.escape(busca)

        filtro["$or"] = [
            {"nome": {"$regex": termo, "$options": "i"}},
            {"marca": {"$regex": termo, "$options": "i"}},
            {"categoria": {"$regex": termo, "$options": "i"}},
            {"fornecedor": {"$regex": termo, "$options": "i"}}
        ]

    if categoria:
        filtro["categoria"] = categoria

    materiais = [
        formatar_material(item)
        for item in colecao.find(filtro).sort("criado_em", -1)
    ]

    todos = list(colecao.find({
        "usuario_id": usuario_id,
        "arquivado": {"$ne": True}
    }))

    todos_formatados = [
        formatar_material(item)
        for item in todos
    ]

    total_materiais = len(todos_formatados)

    total_disponiveis = sum(
        1 for item in todos_formatados
        if item["saldo_equivalente"] > 0
    )

    total_estoque_baixo = sum(
        1 for item in todos_formatados
        if item["estoque_baixo"]
    )

    valor_total_estoque = round(
        sum(item["valor_estoque"] for item in todos_formatados),
        2
    )

    categorias = sorted({
        item.get("categoria", "")
        for item in todos_formatados
        if item.get("categoria")
    })

    if filtro_estoque == "baixo":
        materiais = [
            item for item in materiais
            if item["estoque_baixo"]
        ]

    elif filtro_estoque == "disponivel":
        materiais = [
            item for item in materiais
            if item["saldo_equivalente"] > 0
        ]

    elif filtro_estoque == "zerado":
        materiais = [
            item for item in materiais
            if item["saldo_equivalente"] <= 0
        ]

    movimentacoes = list(
        db["movimentacoes_estoque"]
        .find({"usuario_id": usuario_id})
        .sort("data", -1)
        .limit(10)
    )

    return render_template(
        "materiais.html",
        materiais=materiais,
        busca=busca,
        categoria_selecionada=categoria,
        filtro_estoque=filtro_estoque,
        categorias=categorias,
        total_materiais=total_materiais,
        total_disponiveis=total_disponiveis,
        total_estoque_baixo=total_estoque_baixo,
        valor_total_estoque=valor_total_estoque,
        movimentacoes=movimentacoes
    )


# =====================================================
# CADASTRAR MATERIAL
# =====================================================

@materiais_bp.route("/materiais/novo", methods=["POST"])
def cadastrar_material():
    usuario_id = obter_usuario_id()

    if not usuario_id:
        return redirect(url_for("inicio"))

    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()
    marca = request.form.get("marca", "").strip()
    descricao = request.form.get("descricao", "").strip()
    unidade_medida = request.form.get("unidade_medida", "").strip()
    fornecedor = request.form.get("fornecedor", "").strip()
    localizacao = request.form.get("localizacao", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    try:
        quantidade_unidades = converter_inteiro(
            request.form.get("quantidade_unidades", "0")
        )

        percentual_formulario = validar_percentual(
            request.form.get("percentual_aberto", "100")
        )

        quantidade_fechada, percentual_aberto = (
            converter_estoque_do_formulario(
                quantidade_unidades,
                percentual_formulario
            )
        )

        capacidade = converter_numero(
            request.form.get("capacidade_por_unidade", "1"),
            permitir_zero=False
        )

        valor_unitario = converter_numero(
            request.form.get("valor_unitario")
        )

        estoque_minimo = converter_numero(
            request.form.get("estoque_minimo", "0")
        )

        data_compra = converter_data(
            request.form.get("data_compra", "")
        )

    except (InvalidOperation, ValueError, TypeError):
        flash(
            "Confira os valores numéricos, percentuais e datas.",
            "danger"
        )
        return voltar_para_lista()

    if not nome or not categoria or not unidade_medida:
        flash(
            "Nome, categoria e unidade de medida são obrigatórios.",
            "danger"
        )
        return voltar_para_lista()

    novo_material = {
        "usuario_id": usuario_id,
        "nome": nome,
        "categoria": categoria,
        "marca": marca,
        "descricao": descricao,
        "unidade_medida": unidade_medida,
        "capacidade_por_unidade": capacidade,
        "quantidade_fechada": quantidade_fechada,
        "percentual_aberto": percentual_aberto,
        "valor_unitario": valor_unitario,
        "estoque_minimo": estoque_minimo,
        "fornecedor": fornecedor,
        "data_compra": data_compra,
        "localizacao": localizacao,
        "observacoes": observacoes,
        "arquivado": False,
        "criado_em": agora_utc(),
        "atualizado_em": agora_utc()
    }

    db = get_database()

    try:
        resultado = db["materiais"].insert_one(novo_material)
        novo_material["_id"] = resultado.inserted_id

        saldo = calcular_saldo(
            quantidade_fechada,
            percentual_aberto
        )

        registrar_movimentacao(
            db,
            novo_material,
            "cadastro",
            saldo,
            "Cadastro inicial do material."
        )

        if valor_unitario > 0 and saldo > 0:
            registrar_movimentacao(
                db,
                novo_material,
                "compra",
                saldo,
                "Registro inicial de aquisição do estoque.",
                {
                    "valor_unitario": valor_unitario,
                    "valor_total": round(saldo * valor_unitario, 2),
                    "fornecedor": fornecedor
                }
            )

        flash("Material cadastrado com sucesso!", "success")

    except Exception:
        current_app.logger.exception("Erro ao cadastrar material.")
        flash("Não foi possível cadastrar o material.", "danger")

    return voltar_para_lista()


# =====================================================
# EDITAR MATERIAL
# =====================================================

@materiais_bp.route(
    "/materiais/<material_id>/editar",
    methods=["POST"]
)
def editar_material(material_id):
    material = buscar_material(material_id)

    if not material:
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()
    marca = request.form.get("marca", "").strip()
    descricao = request.form.get("descricao", "").strip()
    unidade_medida = request.form.get("unidade_medida", "").strip()
    fornecedor = request.form.get("fornecedor", "").strip()
    localizacao = request.form.get("localizacao", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    try:
        quantidade_unidades = converter_inteiro(
            request.form.get("quantidade_unidades", "0")
        )

        percentual_formulario = validar_percentual(
            request.form.get("percentual_aberto", "100")
        )

        quantidade_fechada, percentual_aberto = (
            converter_estoque_do_formulario(
                quantidade_unidades,
                percentual_formulario
            )
        )

        capacidade = converter_numero(
            request.form.get("capacidade_por_unidade", "1"),
            permitir_zero=False
        )

        valor_unitario = converter_numero(
            request.form.get("valor_unitario")
        )

        estoque_minimo = converter_numero(
            request.form.get("estoque_minimo", "0")
        )

        data_compra = converter_data(
            request.form.get("data_compra", "")
        )

    except (InvalidOperation, ValueError, TypeError):
        flash(
            "Confira os valores numéricos, percentuais e datas.",
            "danger"
        )
        return voltar_para_lista()

    if not nome or not categoria or not unidade_medida:
        flash(
            "Nome, categoria e unidade de medida são obrigatórios.",
            "danger"
        )
        return voltar_para_lista()

    saldo_anterior = calcular_saldo(
        material.get("quantidade_fechada", 0),
        material.get("percentual_aberto", 0)
    )

    saldo_novo = calcular_saldo(
        quantidade_fechada,
        percentual_aberto
    )

    dados = {
        "nome": nome,
        "categoria": categoria,
        "marca": marca,
        "descricao": descricao,
        "unidade_medida": unidade_medida,
        "capacidade_por_unidade": capacidade,
        "quantidade_fechada": quantidade_fechada,
        "percentual_aberto": percentual_aberto,
        "valor_unitario": valor_unitario,
        "estoque_minimo": estoque_minimo,
        "fornecedor": fornecedor,
        "data_compra": data_compra,
        "localizacao": localizacao,
        "observacoes": observacoes,
        "atualizado_em": agora_utc()
    }

    db = get_database()

    try:
        db["materiais"].update_one(
            {
                "_id": ObjectId(material_id),
                "usuario_id": obter_usuario_id()
            },
            {"$set": dados}
        )

        if saldo_novo != saldo_anterior:
            material_atualizado = dict(material)
            material_atualizado.update(dados)

            registrar_movimentacao(
                db,
                material_atualizado,
                "ajuste",
                round(saldo_novo - saldo_anterior, 2),
                "Ajuste manual do saldo durante a edição."
            )

        flash("Material atualizado com sucesso!", "success")

    except Exception:
        current_app.logger.exception("Erro ao editar material.")
        flash("Não foi possível atualizar o material.", "danger")

    return voltar_para_lista()


# =====================================================
# REGISTRAR CONSUMO
# =====================================================

@materiais_bp.route(
    "/materiais/<material_id>/consumir",
    methods=["POST"]
)
def consumir_material(material_id):
    material = buscar_material(material_id)

    if not material:
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    try:
        percentual_consumido = validar_percentual(
            request.form.get("percentual_consumido")
        )

    except (InvalidOperation, ValueError):
        flash(
            "Selecione um percentual válido, de 10 em 10%.",
            "danger"
        )
        return voltar_para_lista()

    if percentual_consumido <= 0:
        flash("O consumo precisa ser maior que zero.", "warning")
        return voltar_para_lista()

    percentual_atual = material.get("percentual_aberto", 0)
    quantidade_fechada = material.get("quantidade_fechada", 0)

    # Se não existe unidade aberta, abre uma unidade fechada.
    if percentual_atual == 0:

        if quantidade_fechada <= 0:
            flash(
                "Não há unidades disponíveis para consumo.",
                "warning"
            )
            return voltar_para_lista()

        quantidade_fechada -= 1
        percentual_atual = 100

    novo_percentual = percentual_atual - percentual_consumido

    if novo_percentual < 0:
        flash(
            "O consumo informado é maior que o conteúdo disponível "
            "na unidade aberta.",
            "warning"
        )
        return voltar_para_lista()

    # Quando a unidade é totalmente consumida, ela deixa de existir
    # como unidade aberta. A próxima será aberta no próximo consumo.
    if novo_percentual == 0:
        novo_percentual = 0

    db = get_database()

    try:
        db["materiais"].update_one(
            {
                "_id": material["_id"],
                "usuario_id": obter_usuario_id()
            },
            {
                "$set": {
                    "quantidade_fechada": quantidade_fechada,
                    "percentual_aberto": novo_percentual,
                    "atualizado_em": agora_utc()
                }
            }
        )

        material_atualizado = dict(material)

        material_atualizado.update({
            "quantidade_fechada": quantidade_fechada,
            "percentual_aberto": novo_percentual
        })

        registrar_movimentacao(
            db,
            material_atualizado,
            "consumo",
            percentual_consumido,
            f"Consumo de {percentual_consumido}% de uma unidade.",
            {
                "percentual_anterior": percentual_atual,
                "percentual_atual": novo_percentual
            }
        )

        flash(
            "Consumo registrado e estoque atualizado!",
            "success"
        )

    except Exception:
        current_app.logger.exception("Erro ao registrar consumo.")
        flash(
            "Não foi possível registrar o consumo.",
            "danger"
        )

    return voltar_para_lista()


# =====================================================
# ARQUIVAR MATERIAL
# =====================================================

@materiais_bp.route(
    "/materiais/<material_id>/excluir",
    methods=["POST"]
)
def excluir_material(material_id):
    material = buscar_material(material_id)

    if not material:
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    db = get_database()

    try:
        db["materiais"].update_one(
            {
                "_id": material["_id"],
                "usuario_id": obter_usuario_id()
            },
            {
                "$set": {
                    "arquivado": True,
                    "arquivado_em": agora_utc(),
                    "atualizado_em": agora_utc()
                }
            }
        )

        registrar_movimentacao(
            db,
            material,
            "arquivamento",
            0,
            "Material arquivado. O histórico foi preservado."
        )

        flash(
            "Material arquivado. Seu histórico foi preservado.",
            "success"
        )

    except Exception:
        current_app.logger.exception("Erro ao arquivar material.")
        flash(
            "Não foi possível arquivar o material.",
            "danger"
        )

    return voltar_para_lista()