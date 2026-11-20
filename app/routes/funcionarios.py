from datetime import datetime, timezone, timedelta
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


funcionarios_bp = Blueprint("funcionarios", __name__)


TIPOS_REMUNERACAO = ["mensal", "diaria", "servico"]
TIPOS_VINCULO = ["funcionario", "proprietario"]
SITUACOES = ["ativo", "afastado", "desligado"]


def obter_usuario_id():
    return session.get("usuario_id")


def agora_utc():
    return datetime.now(timezone.utc)


def buscar_funcionario(funcionario_id):
    """Busca somente funcionários pertencentes ao usuário autenticado."""
    if not ObjectId.is_valid(funcionario_id):
        return None

    return get_database()["funcionarios"].find_one({
        "_id": ObjectId(funcionario_id),
        "usuario_id": obter_usuario_id(),
        "excluido": {"$ne": True}
    })


def converter_valor(valor):
    """Converte valores digitados no formulário para Decimal."""
    texto = str(valor or "").strip().replace("R$", "").replace(" ", "")

    if not texto:
        raise InvalidOperation

    # Aceita 2500,00 e 2.500,00, além de 2500.00.
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    numero = Decimal(texto)

    if not numero.is_finite() or numero < 0:
        raise InvalidOperation

    return float(numero)


def validar_email(email):
    if not email:
        return True

    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


def voltar_para_lista():
    return redirect(url_for("funcionarios.listar_funcionarios"))


@funcionarios_bp.route("/funcionarios")
def listar_funcionarios():
    usuario_id = obter_usuario_id()

    if not usuario_id:
        return redirect(url_for("inicio"))

    db = get_database()
    colecao = db["funcionarios"]
    agora = agora_utc()
    limite_lixeira = agora - timedelta(days=10)
    vencidos = list(colecao.find({
        "usuario_id": usuario_id, "excluido": True,
        "excluido_em": {"$lte": limite_lixeira}
    }, {"_id": 1}))
    for registro in vencidos:
        colecao.delete_one({"_id": registro["_id"], "usuario_id": usuario_id, "excluido": True})

    busca = request.args.get("busca", "").strip()
    filtro_situacao = request.args.get("situacao", "").strip()

    filtro = {"usuario_id": usuario_id, "excluido": {"$ne": True}}

    if busca:
        termo = re.escape(busca)
        filtro["$or"] = [
            {"nome": {"$regex": termo, "$options": "i"}},
            {"cargo": {"$regex": termo, "$options": "i"}},
            {"email": {"$regex": termo, "$options": "i"}}
        ]

    if filtro_situacao in SITUACOES:
        filtro["situacao"] = filtro_situacao

    configuracao = get_database()["configuracoes"].find_one(
        {"usuario_id": usuario_id}, {"preferencias.ordem_funcionarios": 1}
    ) or {}
    ordem_funcionarios = configuracao.get("preferencias", {}).get("ordem_funcionarios", "nome_asc")
    ordenacao = {
        "nome_asc": [("nome", 1), ("_id", 1)],
        "contratacao_desc": [("data_contratacao", -1), ("nome", 1)],
        "contratacao_asc": [("data_contratacao", 1), ("nome", 1)]
    }.get(ordem_funcionarios, [("nome", 1), ("_id", 1)])
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    por_pagina = 25
    total_registros = colecao.count_documents(filtro)
    total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
    pagina = min(pagina, total_paginas)
    funcionarios = list(colecao.find(filtro).sort(ordenacao).skip((pagina - 1) * por_pagina).limit(por_pagina))
    total_lixeira = colecao.count_documents({"usuario_id": usuario_id, "excluido": True})
    try:
        lixeira_pagina = max(1, int(request.args.get("lixeira_pagina", 1)))
    except (TypeError, ValueError):
        lixeira_pagina = 1
    total_lixeira_paginas = max(1, (total_lixeira + 24) // 25)
    lixeira_pagina = min(lixeira_pagina, total_lixeira_paginas)
    lixeira = list(colecao.find({"usuario_id": usuario_id, "excluido": True}).sort("nome", 1).skip((lixeira_pagina-1)*25).limit(25))

    total_funcionarios = colecao.count_documents({
        "usuario_id": usuario_id,
        "excluido": {"$ne": True}
    })

    total_ativos = colecao.count_documents({
        "usuario_id": usuario_id,
        "situacao": "ativo",
        "excluido": {"$ne": True}
    })

    total_afastados = colecao.count_documents({
        "usuario_id": usuario_id,
        "situacao": "afastado",
        "excluido": {"$ne": True}
    })

    total_desligados = colecao.count_documents({
        "usuario_id": usuario_id,
        "situacao": "desligado",
        "excluido": {"$ne": True}
    })

    # Soma somente remunerações mensais ativas.
    # Diárias e valores por serviço não são comparáveis a salários mensais.
    pipeline = [
        {
            "$match": {
                "usuario_id": usuario_id,
                "situacao": "ativo",
                "tipo_remuneracao": "mensal",
                "excluido": {"$ne": True}
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$valor_remuneracao"}
            }
        }
    ]

    resultado_remuneracao = list(
        colecao.aggregate(pipeline)
    )

    total_remuneracao_mensal = (
        resultado_remuneracao[0]["total"]
        if resultado_remuneracao
        else 0
    )

    return render_template(
        "funcionarios.html",
        funcionarios=funcionarios,
        busca=busca,
        filtro_situacao=filtro_situacao,
        total_funcionarios=total_funcionarios,
        total_ativos=total_ativos,
        total_afastados=total_afastados,
        total_desligados=total_desligados,
        total_remuneracao_mensal=total_remuneracao_mensal,
        ordem_funcionarios=ordem_funcionarios,
        pagina=pagina,
        total_paginas=total_paginas,
        lixeira=lixeira,
        total_lixeira=total_lixeira,
        lixeira_pagina=lixeira_pagina,
        total_lixeira_paginas=total_lixeira_paginas,
        now_date=agora_utc().strftime("%Y-%m-%d")
    )


@funcionarios_bp.route("/funcionarios/novo", methods=["POST"])
def cadastrar_funcionario():
    usuario_id = obter_usuario_id()

    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip().lower()
    cargo = request.form.get("cargo", "").strip()

    tipo_remuneracao = request.form.get(
        "tipo_remuneracao", ""
    ).strip()

    tipo_vinculo = request.form.get(
        "tipo_vinculo", "funcionario"
    ).strip()

    situacao = request.form.get(
        "situacao", "ativo"
    ).strip()

    data_contratacao = request.form.get(
        "data_contratacao", ""
    ).strip()

    observacoes = request.form.get(
        "observacoes", ""
    ).strip()

    if not nome or not cargo or not tipo_remuneracao:
        flash("Preencha nome, função e tipo de remuneração.", "danger")
        return voltar_para_lista()

    if tipo_remuneracao not in TIPOS_REMUNERACAO:
        flash("Tipo de remuneração inválido.", "danger")
        return voltar_para_lista()

    if tipo_vinculo not in TIPOS_VINCULO:
        flash("Tipo de vínculo inválido.", "danger")
        return voltar_para_lista()

    if situacao not in SITUACOES:
        flash("Situação inválida.", "danger")
        return voltar_para_lista()

    if not validar_email(email):
        flash("Informe um endereço de e-mail válido.", "danger")
        return voltar_para_lista()

    try:
        valor_remuneracao = converter_valor(
            request.form.get("valor_remuneracao")
        )
    except (InvalidOperation, ValueError):
        flash("Informe um valor de remuneração válido.", "danger")
        return voltar_para_lista()

    try:
        data_contratacao_obj = (
            datetime.strptime(data_contratacao, "%Y-%m-%d")
            if data_contratacao else None
        )
    except ValueError:
        flash("Informe uma data de contratação válida.", "danger")
        return voltar_para_lista()

    db = get_database()
    colecao = db["funcionarios"]

    if tipo_vinculo == "proprietario":
        proprietario_existente = colecao.find_one({
            "usuario_id": usuario_id,
            "tipo_vinculo": "proprietario",
            "situacao": {"$ne": "desligado"}
        })

        if proprietario_existente:
            flash(
                "Já existe um cadastro ativo para o proprietário.",
                "warning"
            )
            return voltar_para_lista()

        if not ObjectId.is_valid(usuario_id):
            flash("Não foi possível identificar sua conta.", "danger")
            return voltar_para_lista()

        usuario = db["usuarios"].find_one({
            "_id": ObjectId(usuario_id)
        })

        if not usuario:
            flash("Não foi possível localizar sua conta.", "danger")
            return voltar_para_lista()

        # Os dados de identificação do proprietário vêm da conta.
        nome = usuario.get("nome", nome)
        email = usuario.get("email", email)
        telefone = usuario.get("telefone", telefone)

    novo_funcionario = {
        "usuario_id": usuario_id,
        "nome": nome,
        "telefone": telefone,
        "email": email,
        "cargo": cargo,
        "tipo_vinculo": tipo_vinculo,
        "tipo_remuneracao": tipo_remuneracao,
        "valor_remuneracao": valor_remuneracao,
        "data_contratacao": data_contratacao_obj,
        "situacao": situacao,
        "observacoes": observacoes,
        "criado_em": agora_utc(),
        "atualizado_em": agora_utc()
    }

    try:
        colecao.insert_one(novo_funcionario)
        flash("Funcionário cadastrado com sucesso!", "success")

    except Exception:
        current_app.logger.exception(
            "Erro ao cadastrar funcionário."
        )
        flash("Não foi possível cadastrar o funcionário.", "danger")

    return voltar_para_lista()


@funcionarios_bp.route(
    "/funcionarios/<funcionario_id>/editar",
    methods=["POST"]
)
def editar_funcionario(funcionario_id):
    funcionario = buscar_funcionario(funcionario_id)

    if not funcionario:
        flash("Funcionário não encontrado.", "danger")
        return voltar_para_lista()

    nome = request.form.get("nome", "").strip()
    telefone = request.form.get("telefone", "").strip()
    email = request.form.get("email", "").strip().lower()
    cargo = request.form.get("cargo", "").strip()

    tipo_remuneracao = request.form.get(
        "tipo_remuneracao", ""
    ).strip()

    situacao = request.form.get("situacao", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    if not nome or not cargo:
        flash("Nome e função são obrigatórios.", "danger")
        return voltar_para_lista()

    if tipo_remuneracao not in TIPOS_REMUNERACAO:
        flash("Tipo de remuneração inválido.", "danger")
        return voltar_para_lista()

    if situacao not in SITUACOES:
        flash("Situação inválida.", "danger")
        return voltar_para_lista()

    if not validar_email(email):
        flash("Informe um endereço de e-mail válido.", "danger")
        return voltar_para_lista()

    try:
        valor_remuneracao = converter_valor(
            request.form.get("valor_remuneracao")
        )
    except (InvalidOperation, ValueError):
        flash("Informe um valor de remuneração válido.", "danger")
        return voltar_para_lista()

    dados_atualizados = {
        "cargo": cargo,
        "tipo_remuneracao": tipo_remuneracao,
        "valor_remuneracao": valor_remuneracao,
        "situacao": situacao,
        "observacoes": observacoes,
        "atualizado_em": agora_utc()
    }

    # A identificação do proprietário é administrada pela conta.
    if funcionario.get("tipo_vinculo") != "proprietario":
        dados_atualizados.update({
            "nome": nome,
            "telefone": telefone,
            "email": email
        })

    try:
        get_database()["funcionarios"].update_one(
            {
                "_id": ObjectId(funcionario_id),
                "usuario_id": obter_usuario_id()
            },
            {"$set": dados_atualizados}
        )

        flash("Cadastro atualizado com sucesso!", "success")

    except Exception:
        current_app.logger.exception(
            "Erro ao atualizar funcionário."
        )
        flash("Não foi possível atualizar o cadastro.", "danger")

    return voltar_para_lista()


@funcionarios_bp.route(
    "/funcionarios/<funcionario_id>/desligar",
    methods=["POST"]
)
def desligar_funcionario(funcionario_id):
    funcionario = buscar_funcionario(funcionario_id)

    if not funcionario:
        flash("Funcionário não encontrado.", "danger")
        return voltar_para_lista()

    if funcionario.get("tipo_vinculo") == "proprietario":
        flash(
            "O cadastro do proprietário não pode ser desligado por esta opção.",
            "warning"
        )
        return voltar_para_lista()

    try:
        get_database()["funcionarios"].update_one(
            {
                "_id": ObjectId(funcionario_id),
                "usuario_id": obter_usuario_id()
            },
            {
                "$set": {
                    "situacao": "desligado",
                    "atualizado_em": agora_utc()
                }
            }
        )

        flash(
            "Funcionário desligado. O histórico do cadastro foi preservado.",
            "success"
        )

    except Exception:
        current_app.logger.exception(
            "Erro ao desligar funcionário."
        )
        flash("Não foi possível desligar o funcionário.", "danger")

    return voltar_para_lista()

# =========================================================
# PAGAMENTOS, VALES E HISTÓRICO FINANCEIRO DO FUNCIONÁRIO
# =========================================================

def registrar_despesa_funcionario(funcionario, tipo, valor, data_pagamento, descricao):
    db = get_database()
    usuario = obter_usuario_id()
    from app.services.financeiro_service import preparar_movimentacao
    registro = preparar_movimentacao(
        db, usuario, "saida", "funcionarios", descricao, valor,
        data_pagamento, status="realizado", forma_pagamento="nao_informado",
        funcionario_id=funcionario["_id"], funcionario_nome=funcionario.get("nome", ""),
        origem="folha_funcionario", subtipo_funcionario=tipo,
        observacoes="Despesa registrada pelo módulo de Funcionários."
    )
    db["movimentacoes_financeiras"].insert_one(registro)


@funcionarios_bp.route("/funcionarios/<funcionario_id>/pagamento", methods=["POST"])
def registrar_pagamento_funcionario(funcionario_id):
    funcionario = buscar_funcionario(funcionario_id)
    if not funcionario:
        flash("Funcionário não encontrado.", "danger")
        return voltar_para_lista()
    try:
        data_pagamento = datetime.strptime(request.form.get("data_pagamento", ""), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        valor = float(funcionario.get("valor_remuneracao", 0) or 0) if request.form.get("usar_remuneracao") == "on" else converter_valor(request.form.get("valor"))
        if valor <= 0:
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        flash("Informe um valor e uma data de pagamento válidos.", "danger")
        return voltar_para_lista()
    registrar_despesa_funcionario(funcionario, "salario", valor, data_pagamento, f"Pagamento de {funcionario.get('nome', 'funcionário')}")
    flash("Pagamento registrado e lançado nas despesas do Financeiro.", "success")
    return voltar_para_lista()


@funcionarios_bp.route("/funcionarios/<funcionario_id>/vale", methods=["POST"])
def registrar_vale_funcionario(funcionario_id):
    funcionario = buscar_funcionario(funcionario_id)
    if not funcionario:
        flash("Funcionário não encontrado.", "danger")
        return voltar_para_lista()
    tipo = request.form.get("tipo_vale", "")
    if tipo not in ("adiantamento", "vr", "vt"):
        flash("Selecione um tipo de vale válido.", "danger")
        return voltar_para_lista()
    try:
        data_pagamento = datetime.strptime(request.form.get("data_pagamento", ""), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        valor = converter_valor(request.form.get("valor"))
        if valor <= 0:
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        flash("Informe um valor e uma data válidos.", "danger")
        return voltar_para_lista()
    nomes = {"adiantamento": "Adiantamento", "vr": "Vale-refeição", "vt": "Vale-transporte"}
    registrar_despesa_funcionario(funcionario, tipo, valor, data_pagamento, f"{nomes[tipo]}: {funcionario.get('nome', 'funcionário')}")
    flash(f"{nomes[tipo]} registrado e lançado no Financeiro.", "success")
    return voltar_para_lista()


@funcionarios_bp.route("/funcionarios/<funcionario_id>/despesas")
def despesas_funcionario(funcionario_id):
    funcionario = buscar_funcionario(funcionario_id)
    if not funcionario:
        flash("Funcionário não encontrado.", "danger")
        return voltar_para_lista()
    db = get_database()
    competencia = request.args.get("competencia", datetime.now().strftime("%Y-%m")).strip()
    filtro = {"usuario_id": obter_usuario_id(), "funcionario_id": funcionario["_id"], "competencia": competencia, "tipo": "saida"}
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total = db["movimentacoes_financeiras"].count_documents(filtro)
    por_pagina = 25
    paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina = min(pagina, paginas)
    movimentos = list(db["movimentacoes_financeiras"].find(filtro).sort("data_movimento", -1).skip((pagina-1)*por_pagina).limit(por_pagina))
    return render_template("funcionario_despesas.html", funcionario=funcionario, movimentos=movimentos, competencia=competencia, pagina=pagina, total_paginas=paginas, total=total)


@funcionarios_bp.route("/funcionarios/<funcionario_id>/excluir", methods=["POST"])
def enviar_funcionario_lixeira(funcionario_id):
    funcionario = buscar_funcionario(funcionario_id)
    if not funcionario:
        flash("Funcionário não encontrado.", "danger")
        return voltar_para_lista()
    if funcionario.get("tipo_vinculo") == "proprietario":
        flash("O cadastro do proprietário não pode ser excluído.", "warning")
        return voltar_para_lista()
    agora = agora_utc()
    get_database()["funcionarios"].update_one(
        {"_id": funcionario["_id"], "usuario_id": obter_usuario_id()},
        {"$set": {"excluido": True, "excluido_em": agora, "atualizado_em": agora}}
    )
    flash("Funcionário enviado à lixeira. O cadastro será excluído permanentemente após 10 dias; movimentações financeiras serão preservadas.", "success")
    return voltar_para_lista()


@funcionarios_bp.route("/funcionarios/<funcionario_id>/restaurar", methods=["POST"])
def restaurar_funcionario(funcionario_id):
    if not ObjectId.is_valid(funcionario_id):
        return voltar_para_lista()
    get_database()["funcionarios"].update_one(
        {"_id": ObjectId(funcionario_id), "usuario_id": obter_usuario_id(), "excluido": True},
        {"$unset": {"excluido": "", "excluido_em": ""}, "$set": {"atualizado_em": agora_utc()}}
    )
    flash("Funcionário restaurado.", "success")
    return voltar_para_lista()
