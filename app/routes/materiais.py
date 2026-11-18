from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import re
import time

from bson import ObjectId
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    current_app,
    jsonify
)

from app.database.connection import get_database


materiais_bp = Blueprint("materiais", __name__)

PERCENTUAIS_VALIDOS = set(range(0, 101, 10))


def obter_usuario_id():
    return session.get("usuario_id")


def agora_utc():
    return datetime.now(timezone.utc)


_ULTIMA_LIMPEZA_MATERIAIS = {}


def processar_prazos_materiais(db=None, usuario_id=None):
    """
    Aplica a política de retenção sempre que a tela de materiais é acessada:
    - Arquivados há 10 dias: movidos automaticamente para a lixeira.
    - Na lixeira há 10 dias: cadastro removido permanentemente.
    As movimentações são preservadas para o futuro ERP.
    """
    db = db or get_database()
    agora = agora_utc()
    limite = agora - timedelta(days=10)
    materiais = db["materiais"]

    filtro_usuario = {"usuario_id": usuario_id} if usuario_id else {}

    vencidos_arquivados = list(materiais.find({
        **filtro_usuario,
        "arquivado": True,
        "excluido": {"$ne": True},
        "arquivado_em": {"$lte": limite}
    }))

    for material in vencidos_arquivados:
        resultado = materiais.update_one(
            {
                "_id": material["_id"],
                "usuario_id": material.get("usuario_id"),
                "arquivado": True,
                "excluido": {"$ne": True},
                "arquivado_em": {"$lte": limite}
            },
            {"$set": {
                "excluido": True,
                "arquivado_antes_lixeira": True,
                "excluido_em": agora,
                "atualizado_em": agora
            }}
        )

        if resultado.modified_count:
            registro = {
                "usuario_id": material.get("usuario_id"),
                "material_id": material["_id"],
                "material_nome": material.get("nome", "Material"),
                "tipo": "exclusao_automatica",
                "quantidade": 0,
                "descricao": "Material movido automaticamente para a lixeira após 10 dias arquivado.",
                "data": agora,
                "responsavel": "Sistema TaskBerry"
            }
            db["movimentacoes_estoque"].insert_one(registro)

    vencidos_lixeira = list(materiais.find({
        **filtro_usuario,
        "excluido": True,
        "excluido_em": {"$lte": limite}
    }, {"_id": 1, "usuario_id": 1}))

    for material in vencidos_lixeira:
        materiais.delete_one({
            "_id": material["_id"],
            "usuario_id": material.get("usuario_id"),
            "excluido": True,
            "excluido_em": {"$lte": limite}
        })
        # Não excluir movimentacoes_estoque: compras e despesas históricas
        # continuarão disponíveis para os relatórios do ERP.


@materiais_bp.before_app_request
def executar_limpeza_automatica_materiais():
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        return

    agora_monotonico = time.monotonic()
    ultima_execucao = _ULTIMA_LIMPEZA_MATERIAIS.get(str(usuario_id), 0)

    # Evita consultar o banco em todas as requisições e carregamentos de arquivos.
    if agora_monotonico - ultima_execucao < 300:
        return

    _ULTIMA_LIMPEZA_MATERIAIS[str(usuario_id)] = agora_monotonico

    try:
        processar_prazos_materiais(get_database(), usuario_id)
    except Exception:
        current_app.logger.exception("Erro na rotina automática de retenção de materiais.")


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
        filtro["excluido"] = {"$ne": True}

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
        "arquivado": {"$ne": True},
        "excluido": {"$ne": True}
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

    configuracao = db["configuracoes"].find_one(
        {"usuario_id": usuario_id}, {"preferencias.ordem_materiais": 1}
    ) or {}
    ordem_materiais = configuracao.get("preferencias", {}).get("ordem_materiais", "atualizado_desc")
    ordenacao = {
        "atualizado_desc": [("atualizado_em", -1), ("_id", -1)],
        "atualizado_asc": [("atualizado_em", 1), ("_id", 1)]
    }.get(ordem_materiais, [("atualizado_em", -1), ("_id", -1)])
    materiais = [
        formatar_material(item)
        for item in colecao.find(filtro).sort(ordenacao)
    ]

    todos = list(colecao.find({
        "usuario_id": usuario_id,
        "arquivado": {"$ne": True},
        "excluido": {"$ne": True}
    }))
    todos_formatados = [formatar_material(item) for item in todos]

    total_materiais = len(todos_formatados)
    total_disponiveis = sum(1 for item in todos_formatados if item["saldo_equivalente"] > 0)
    total_estoque_baixo = sum(1 for item in todos_formatados if item["estoque_baixo"])
    valor_total_estoque = round(sum(item["valor_estoque"] for item in todos_formatados), 2)

    categorias = sorted({
        item.get("categoria", "")
        for item in todos_formatados
        if item.get("categoria")
    })

    if filtro_estoque == "baixo":
        materiais = [item for item in materiais if item["estoque_baixo"]]
    elif filtro_estoque == "disponivel":
        materiais = [item for item in materiais if item["saldo_equivalente"] > 0]
    elif filtro_estoque == "zerado":
        materiais = [item for item in materiais if item["saldo_equivalente"] <= 0]

    materiais_arquivados = [
        formatar_material(item)
        for item in colecao.find({
            "usuario_id": usuario_id,
            "arquivado": True,
            "excluido": {"$ne": True}
        }).sort("arquivado_em", -1)
    ]

    materiais_lixeira = [
        formatar_material(item)
        for item in colecao.find({
            "usuario_id": usuario_id,
            "excluido": True
        }).sort("excluido_em", -1)
    ]

    consulta_movimentacoes = db["movimentacoes_estoque"].find(
        {"usuario_id": usuario_id}
    ).sort("data", -1)

    movimentacoes = list(consulta_movimentacoes.limit(5))
    movimentacoes_tem_mais = db["movimentacoes_estoque"].count_documents(
        {"usuario_id": usuario_id}
    ) > 5

    material_recompra = None
    recompra_id = request.args.get("recomprar", "").strip()
    if recompra_id and ObjectId.is_valid(recompra_id):
        candidato = colecao.find_one({
            "_id": ObjectId(recompra_id),
            "usuario_id": usuario_id,
            "arquivado": {"$ne": True},
            "excluido": {"$ne": True}
        })
        if candidato:
            candidato = formatar_material(candidato)
            if candidato["saldo_equivalente"] <= 0:
                material_recompra = candidato
            else:
                flash("Este material ainda possui saldo em estoque. A nova compra não foi aberta.", "info")

    return render_template(
        "materiais.html",
        materiais=materiais,
        material_recompra=material_recompra,
        materiais_arquivados=materiais_arquivados,
        materiais_lixeira=materiais_lixeira,
        busca=busca,
        categoria_selecionada=categoria,
        filtro_estoque=filtro_estoque,
        categorias=categorias,
        total_materiais=total_materiais,
        total_disponiveis=total_disponiveis,
        total_estoque_baixo=total_estoque_baixo,
        valor_total_estoque=valor_total_estoque,
        movimentacoes=movimentacoes,
        movimentacoes_tem_mais=movimentacoes_tem_mais,
        ordem_materiais=ordem_materiais
    )



# =====================================================
# CARREGAR MAIS MOVIMENTAÇÕES (10 POR VEZ)
# =====================================================

@materiais_bp.route("/materiais/movimentacoes/mais")
def carregar_mais_movimentacoes():
    usuario_id = obter_usuario_id()
    if not usuario_id:
        return jsonify({"items": [], "has_more": False}), 401

    try:
        skip = max(0, int(request.args.get("skip", 0)))
    except (TypeError, ValueError):
        skip = 0

    db = get_database()
    cursor = (
        db["movimentacoes_estoque"]
        .find({"usuario_id": usuario_id})
        .sort("data", -1)
        .skip(skip)
        .limit(11)
    )
    registros = list(cursor)
    has_more = len(registros) > 10
    registros = registros[:10]

    items = []
    for item in registros:
        data = item.get("data")
        if data and data.tzinfo is None:
            data = data.replace(tzinfo=timezone.utc)
        items.append({
            "material_nome": item.get("material_nome", "Material"),
            "descricao": item.get("descricao", ""),
            "responsavel": item.get("responsavel", "Usuário"),
            "data": data.strftime("%d/%m/%Y %H:%M") if data else "",
            "tipo": item.get("tipo", "movimentacao")
        })

    return jsonify({"items": items, "has_more": has_more})


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
        "excluido": False,
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
# REGISTRAR NOVA COMPRA DE MATERIAL EXISTENTE
# =====================================================

@materiais_bp.route("/materiais/<material_id>/comprar", methods=["POST"])
def registrar_compra_material(material_id):
    material = buscar_material(material_id)

    if not material:
        flash("Material não encontrado no estoque ativo.", "danger")
        return voltar_para_lista()

    saldo_atual = calcular_saldo(
        material.get("quantidade_fechada", 0),
        material.get("percentual_aberto", 0)
    )
    if saldo_atual > 0:
        flash("Este material ainda possui estoque. A compra não foi registrada.", "warning")
        return voltar_para_lista()

    try:
        quantidade_unidades = converter_inteiro(
            request.form.get("quantidade_unidades", "0"), minimo=1
        )
        percentual_formulario = validar_percentual(
            request.form.get("percentual_aberto", "100")
        )
        quantidade_fechada, percentual_aberto = converter_estoque_do_formulario(
            quantidade_unidades, percentual_formulario
        )
        valor_unitario = converter_numero(
            request.form.get("valor_unitario", ""), permitir_zero=False
        )
        data_compra = converter_data(request.form.get("data_compra", ""))
    except (InvalidOperation, ValueError, TypeError):
        flash("Informe uma quantidade, um valor unitário válido e confira a data da compra.", "danger")
        return redirect(url_for("materiais.listar_materiais", recompra=material_id))

    saldo_comprado = calcular_saldo(quantidade_fechada, percentual_aberto)
    if saldo_comprado <= 0:
        flash("A quantidade comprada precisa ser maior que zero.", "warning")
        return redirect(url_for("materiais.listar_materiais", recompra=material_id))

    fornecedor = request.form.get("fornecedor", "").strip()
    agora = agora_utc()
    db = get_database()

    dados_atualizados = {
        "quantidade_fechada": quantidade_fechada,
        "percentual_aberto": percentual_aberto,
        "valor_unitario": valor_unitario,
        "atualizado_em": agora
    }
    if fornecedor:
        dados_atualizados["fornecedor"] = fornecedor
    if data_compra:
        dados_atualizados["data_compra"] = data_compra

    try:
        resultado = db["materiais"].update_one(
            {
                "_id": material["_id"],
                "usuario_id": obter_usuario_id(),
                "arquivado": {"$ne": True},
                "excluido": {"$ne": True},
                "quantidade_fechada": material.get("quantidade_fechada", 0),
                "percentual_aberto": material.get("percentual_aberto", 0)
            },
            {"$set": dados_atualizados}
        )

        if resultado.matched_count == 0:
            flash("O estoque foi alterado enquanto você registrava a compra. Atualize a página e tente novamente.", "warning")
            return voltar_para_lista()

        material_atualizado = dict(material)
        material_atualizado.update(dados_atualizados)

        registrar_movimentacao(
            db,
            material_atualizado,
            "compra_reabastecimento",
            saldo_comprado,
            "Nova compra registrada para reabastecer um material existente.",
            {
                "valor_unitario": valor_unitario,
                "valor_total": round(saldo_comprado * valor_unitario, 2),
                "fornecedor": fornecedor,
                "data_compra": data_compra
            }
        )

        flash(f"Compra registrada! O estoque de {material.get('nome', 'material')} foi atualizado.", "success")

    except Exception:
        current_app.logger.exception("Erro ao registrar nova compra de material.")
        flash("Não foi possível registrar a compra do material.", "danger")

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

    quantidade_fechada = int(material.get("quantidade_fechada", 0))
    percentual_atual = int(material.get("percentual_aberto", 0))
    unidade_finalizada = request.form.get("unidade_finalizada") == "1"
    estoque_total_finalizado = request.form.get("estoque_total_finalizado") == "1"

    if unidade_finalizada and estoque_total_finalizado:
        flash("Escolha apenas uma opção de finalização.", "warning")
        return voltar_para_lista()

    if estoque_total_finalizado:
        saldo_anterior = calcular_saldo(quantidade_fechada, percentual_atual)
        if saldo_anterior <= 0:
            flash("Este material já está com o estoque zerado.", "warning")
            return voltar_para_lista()

        quantidade_fechada_nova = 0
        percentual_novo = 0
        tipo_movimentacao = "estoque_zerado"
        quantidade_movimentada = saldo_anterior
        percentual_anterior = percentual_atual
        descricao = (
            f"Todo o estoque foi finalizado. {quantidade_fechada} unidade(s) fechada(s) "
            f"e o conteúdo restante da unidade aberta foram retirados do saldo."
        )

    elif unidade_finalizada:
        if percentual_atual > 0:
            quantidade_fechada_nova = quantidade_fechada
            percentual_novo = 0
            quantidade_movimentada = percentual_atual / 100
            percentual_anterior = percentual_atual
            descricao = "Unidade aberta finalizada. Todo o conteúdo restante foi utilizado."
        elif quantidade_fechada > 0:
            quantidade_fechada_nova = quantidade_fechada - 1
            percentual_novo = 0
            quantidade_movimentada = 1
            percentual_anterior = 100
            descricao = "Uma unidade fechada foi totalmente utilizada e retirada do estoque."
        else:
            flash("Não há unidades disponíveis para finalizar.", "warning")
            return voltar_para_lista()

        tipo_movimentacao = "unidade_finalizada"

    else:
        try:
            percentual_consumido = validar_percentual(
                request.form.get("percentual_consumido")
            )
        except (InvalidOperation, ValueError):
            flash("Selecione um percentual válido ou uma opção de finalização.", "danger")
            return voltar_para_lista()

        if percentual_consumido <= 0:
            flash("O consumo precisa ser maior que zero.", "warning")
            return voltar_para_lista()

        if percentual_atual == 0:
            if quantidade_fechada <= 0:
                flash("Não há unidades disponíveis para consumo.", "warning")
                return voltar_para_lista()
            quantidade_fechada -= 1
            percentual_atual = 100

        novo_percentual = percentual_atual - percentual_consumido
        if novo_percentual < 0:
            flash("O consumo informado é maior que o conteúdo disponível na unidade aberta.", "warning")
            return voltar_para_lista()

        quantidade_fechada_nova = quantidade_fechada
        percentual_novo = novo_percentual
        tipo_movimentacao = "consumo"
        quantidade_movimentada = percentual_consumido
        percentual_anterior = percentual_atual
        descricao = f"Consumo de {percentual_consumido}% de uma unidade."

    db = get_database()

    try:
        resultado = db["materiais"].update_one(
            {
                "_id": material["_id"],
                "usuario_id": obter_usuario_id(),
                "arquivado": {"$ne": True},
                "excluido": {"$ne": True}
            },
            {"$set": {
                "quantidade_fechada": quantidade_fechada_nova,
                "percentual_aberto": percentual_novo,
                "atualizado_em": agora_utc()
            }}
        )

        if resultado.matched_count == 0:
            flash("Não foi possível atualizar este material.", "danger")
            return voltar_para_lista()

        material_atualizado = dict(material)
        material_atualizado.update({
            "quantidade_fechada": quantidade_fechada_nova,
            "percentual_aberto": percentual_novo
        })

        registrar_movimentacao(
            db,
            material_atualizado,
            tipo_movimentacao,
            quantidade_movimentada,
            descricao,
            {
                "percentual_anterior": percentual_anterior,
                "percentual_atual": percentual_novo,
                "unidade_totalmente_utilizada": unidade_finalizada,
                "estoque_total_finalizado": estoque_total_finalizado
            }
        )

        if estoque_total_finalizado:
            flash("Todo o estoque foi zerado e registrado no histórico!", "success")
        elif unidade_finalizada:
            flash("Unidade finalizada e registrada no histórico!", "success")
        else:
            flash("Consumo registrado e estoque atualizado!", "success")

    except Exception:
        current_app.logger.exception("Erro ao registrar consumo do material.")
        flash("Não foi possível registrar a movimentação do material.", "danger")

    return voltar_para_lista()


# =====================================================
# ARQUIVAR MATERIAL
# =====================================================

@materiais_bp.route("/materiais/<material_id>/arquivar", methods=["POST"])
def arquivar_material(material_id):
    material = buscar_material(material_id)
    if not material:
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    agora = agora_utc()
    db = get_database()
    db["materiais"].update_one(
        {"_id": material["_id"], "usuario_id": obter_usuario_id(), "excluido": {"$ne": True}},
        {"$set": {"arquivado": True, "arquivado_em": agora, "atualizado_em": agora}}
    )
    registrar_movimentacao(db, material, "arquivamento", 0, "Material arquivado. Cadastro e histórico preservados.")
    flash("Material arquivado. Você pode restaurá-lo na seção Arquivados.", "success")
    return voltar_para_lista()


# Compatibilidade com formulários antigos que ainda apontem para /excluir.
@materiais_bp.route("/materiais/<material_id>/excluir", methods=["POST"])
def excluir_material(material_id):
    return arquivar_material(material_id)


# =====================================================
# ENVIAR MATERIAL PARA A LIXEIRA
# =====================================================

@materiais_bp.route("/materiais/<material_id>/lixeira", methods=["POST"])
def enviar_material_lixeira(material_id):
    material = buscar_material(material_id, incluir_arquivados=True)
    if not material or material.get("excluido") is True:
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    agora = agora_utc()
    db = get_database()
    db["materiais"].update_one(
        {"_id": material["_id"], "usuario_id": obter_usuario_id()},
        {"$set": {
            "excluido": True,
            "arquivado_antes_lixeira": material.get("arquivado", False),
            "excluido_em": agora,
            "atualizado_em": agora
        }}
    )
    registrar_movimentacao(db, material, "exclusao", 0, "Material enviado para a lixeira. O cadastro e o histórico foram preservados.")
    flash("Material enviado para a lixeira.", "success")
    return voltar_para_lista()


# =====================================================
# RESTAURAR MATERIAL
# =====================================================

@materiais_bp.route("/materiais/<material_id>/restaurar", methods=["POST"])
def restaurar_material(material_id):
    if not ObjectId.is_valid(material_id):
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    db = get_database()
    material = db["materiais"].find_one({
        "_id": ObjectId(material_id),
        "usuario_id": obter_usuario_id(),
        "$or": [{"arquivado": True}, {"excluido": True}]
    })
    if not material:
        flash("Material não encontrado para restauração.", "danger")
        return voltar_para_lista()

    estava_na_lixeira = material.get("excluido") is True
    arquivado_antes = material.get("arquivado_antes_lixeira", False) if estava_na_lixeira else False
    agora = agora_utc()
    db["materiais"].update_one(
        {"_id": material["_id"], "usuario_id": obter_usuario_id()},
        {"$set": {
            "excluido": False,
            "arquivado": bool(arquivado_antes),
            "arquivado_em": agora if arquivado_antes else None,
            "atualizado_em": agora
        }, "$unset": {"excluido_em": "", "arquivado_antes_lixeira": ""}}
    )
    registrar_movimentacao(db, material, "restauracao", 0, "Material restaurado.")
    if arquivado_antes:
        flash("Material restaurado para a área de arquivados.", "success")
    else:
        flash("Material restaurado para o estoque ativo.", "success")
    return voltar_para_lista()


# =====================================================
# EXCLUSÃO PERMANENTE
# =====================================================

@materiais_bp.route("/materiais/<material_id>/excluir-permanentemente", methods=["POST"])
def excluir_material_permanentemente(material_id):
    if not ObjectId.is_valid(material_id):
        flash("Material não encontrado.", "danger")
        return voltar_para_lista()

    db = get_database()
    material = db["materiais"].find_one({
        "_id": ObjectId(material_id),
        "usuario_id": obter_usuario_id(),
        "excluido": True
    })
    if not material:
        flash("Somente materiais que estão na lixeira podem ser excluídos permanentemente.", "warning")
        return voltar_para_lista()

    db["materiais"].delete_one({"_id": material["_id"], "usuario_id": obter_usuario_id(), "excluido": True})
    # As movimentações são preservadas para não apagar o histórico de estoque.
    flash("Cadastro excluído permanentemente. O histórico de movimentações foi preservado.", "success")
    return voltar_para_lista()