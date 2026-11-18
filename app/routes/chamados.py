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


chamados_bp = Blueprint("chamados", __name__)


# =========================================================
# CONFIGURAÇÕES E FUNÇÕES AUXILIARES
# =========================================================

STATUS_CHAMADO = {
    "a_iniciar": "A iniciar",
    "em_andamento": "Em andamento",
    "aguardando": "Aguardando",
    "concluido": "Concluído"
}

PRIORIDADES = {
    "baixa": "Baixa",
    "normal": "Normal",
    "alta": "Alta",
    "urgente": "Urgente"
}


def obter_usuario_id():
    return session.get("usuario_id")


def agora():
    return datetime.now(timezone.utc)


def voltar_para_lista():
    return redirect(url_for("chamados.listar_chamados"))


def converter_data(valor, obrigatoria=False):
    valor = (valor or "").strip()

    if not valor:
        if obrigatoria:
            raise ValueError("Preencha as datas obrigatórias.")
        return None

    try:
        data = datetime.strptime(valor, "%Y-%m-%d")
        return data.replace(tzinfo=timezone.utc)

    except ValueError:
        raise ValueError("Uma das datas informadas é inválida.")


def data_para_input(valor):
    if not valor:
        return ""

    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")

    return str(valor)[:10]


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
        raise ValueError("Informe um valor financeiro válido.")

    if numero < 0:
        raise ValueError("O valor não pode ser negativo.")

    return float(numero.quantize(Decimal("0.01")))


def obter_meses_disponiveis(colecao, usuario_id):
    pipeline = [
        {
            "$match": {
                "usuario_id": usuario_id
            }
        },
        {
            "$group": {
                "_id": "$competencia"
            }
        },
        {
            "$sort": {
                "_id": -1
            }
        }
    ]

    meses = [
        item["_id"]
        for item in colecao.aggregate(pipeline)
        if item.get("_id")
    ]

    return meses


def formatar_competencia(valor):
    if not valor or len(valor) != 7:
        return valor or ""

    try:
        data = datetime.strptime(valor, "%Y-%m")
        meses = [
            "janeiro", "fevereiro", "março", "abril",
            "maio", "junho", "julho", "agosto",
            "setembro", "outubro", "novembro", "dezembro"
        ]

        return f"{meses[data.month - 1].capitalize()} de {data.year}"

    except ValueError:
        return valor


def buscar_chamado(chamado_id):
    if not ObjectId.is_valid(chamado_id):
        return None

    return get_database()["chamados"].find_one({
        "_id": ObjectId(chamado_id),
        "usuario_id": obter_usuario_id()
    })


def carregar_clientes():
    db = get_database()
    configuracao = db["configuracoes"].find_one(
        {"usuario_id": obter_usuario_id()}, {"preferencias.incluir_clientes_arquivados_excluidos": 1}
    ) or {}
    incluir_inativos = configuracao.get("preferencias", {}).get(
        "incluir_clientes_arquivados_excluidos", False
    )
    filtro = {"usuario_id": obter_usuario_id()}
    if not incluir_inativos:
        filtro.update({"arquivado": {"$ne": True}, "excluido": {"$ne": True}})
    clientes = list(db["clientes"].find(filtro).sort("nome", 1))
    for cliente in clientes:
        if cliente.get("excluido"):
            cliente["status_cadastro"] = "Na lixeira"
        elif cliente.get("arquivado"):
            cliente["status_cadastro"] = "Arquivado"
        else:
            cliente["status_cadastro"] = "Ativo"
    return clientes


def carregar_funcionarios():
    return list(
        get_database()["funcionarios"].find(
            {
                "usuario_id": obter_usuario_id(),
                "situacao": "ativo"
            }
        ).sort("nome", 1)
    )


def obter_cliente_valido(cliente_id):
    if not ObjectId.is_valid(cliente_id or ""):
        return None

    db = get_database()
    cliente = db["clientes"].find_one({
        "_id": ObjectId(cliente_id),
        "usuario_id": obter_usuario_id()
    })
    if not cliente:
        return None
    configuracao = db["configuracoes"].find_one(
        {"usuario_id": obter_usuario_id()}, {"preferencias.incluir_clientes_arquivados_excluidos": 1}
    ) or {}
    incluir_inativos = configuracao.get("preferencias", {}).get(
        "incluir_clientes_arquivados_excluidos", False
    )
    if not incluir_inativos and (cliente.get("arquivado") or cliente.get("excluido")):
        return None
    return cliente


def obter_funcionarios_validos(ids):
    ids_validos = []

    for item in ids:
        if ObjectId.is_valid(item):
            ids_validos.append(ObjectId(item))

    if not ids_validos:
        return []

    funcionarios = list(
        get_database()["funcionarios"].find({
            "_id": {"$in": ids_validos},
            "usuario_id": obter_usuario_id(),
            "situacao": "ativo"
        })
    )

    return [
        {
            "funcionario_id": str(funcionario["_id"]),
            "nome": funcionario.get("nome", ""),
            "cargo": funcionario.get("cargo", "")
        }
        for funcionario in funcionarios
    ]



def carregar_materiais_disponiveis():
    return list(get_database()["materiais"].find({
        "usuario_id": obter_usuario_id(), "arquivado": {"$ne": True}
    }).sort("nome", 1))


def carregar_ferramentas_disponiveis(chamado=None):
    filtro = {
        "usuario_id": obter_usuario_id(),
        "arquivada": {"$ne": True},
        "situacao": "disponivel"
    }
    ferramentas = list(get_database()["ferramentas"].find(filtro).sort("nome", 1))
    ids_atuais = {item.get("ferramenta_id") for item in (chamado or {}).get("ferramentas_previstas", [])}
    if ids_atuais:
        atuais = list(get_database()["ferramentas"].find({
            "usuario_id": obter_usuario_id(), "arquivada": {"$ne": True},
            "_id": {"$in": [ObjectId(x) for x in ids_atuais if ObjectId.is_valid(x)]}
        }))
        mapa = {str(x["_id"]): x for x in ferramentas}
        mapa.update({str(x["_id"]): x for x in atuais})
        ferramentas = list(mapa.values())
    return ferramentas


def obter_associacoes_previstas():
    db = get_database()
    materiais_ids = request.form.getlist("materiais_ids")
    ferramentas_ids = request.form.getlist("ferramentas_ids")
    quantidades = request.form.getlist("materiais_quantidades")
    ids_m = [ObjectId(x) for x in materiais_ids if ObjectId.is_valid(x)]
    materiais = list(db["materiais"].find({
        "_id": {"$in": ids_m}, "usuario_id": obter_usuario_id(),
        "arquivado": {"$ne": True}
    })) if ids_m else []
    if len(materiais) != len(set(materiais_ids)):
        raise ValueError("Um ou mais materiais selecionados não são válidos.")
    previstos_m = []
    for material in materiais:
        indice = materiais_ids.index(str(material["_id"]))
        try:
            quantidade = float((quantidades[indice] if indice < len(quantidades) else "1").replace(",", "."))
        except (ValueError, AttributeError):
            raise ValueError("Informe uma quantidade válida para cada material.")
        if quantidade <= 0:
            raise ValueError("A quantidade prevista deve ser maior que zero.")
        previstos_m.append({"material_id": str(material["_id"]), "nome": material.get("nome", "Material"),
            "unidade_medida": material.get("unidade_medida", "unidade"), "quantidade_prevista": quantidade,
            "consumo_registrado": False})
    ids_f = [ObjectId(x) for x in ferramentas_ids if ObjectId.is_valid(x)]
    ferramentas = list(db["ferramentas"].find({
        "_id": {"$in": ids_f}, "usuario_id": obter_usuario_id(),
        "arquivada": {"$ne": True}, "situacao": "disponivel"
    })) if ids_f else []
    if len(ferramentas) != len(set(ferramentas_ids)):
        raise ValueError("Uma ou mais ferramentas não estão disponíveis ou não pertencem à sua conta.")
    previstos_f = [{"ferramenta_id": str(item["_id"]), "nome": item.get("nome", "Ferramenta"),
        "codigo": item.get("codigo", ""), "situacao_no_vinculo": item.get("situacao", "disponivel")} for item in ferramentas]
    return previstos_m, previstos_f


def preparar_dados_formulario():
    titulo = request.form.get("titulo", "").strip()
    descricao = request.form.get("descricao", "").strip()
    cliente_id = request.form.get("cliente_id", "").strip()

    prioridade = request.form.get("prioridade", "normal").strip()
    status = request.form.get("status", "a_iniciar").strip()

    data_inicio = converter_data(
        request.form.get("data_inicio"),
        obrigatoria=True
    )

    previsao_termino = converter_data(
        request.form.get("previsao_termino"),
        obrigatoria=True
    )

    if not titulo:
        raise ValueError("Informe o nome ou título da obra.")

    if not cliente_id:
        raise ValueError("Selecione um cliente.")

    if prioridade not in PRIORIDADES:
        raise ValueError("Selecione uma prioridade válida.")

    if status not in STATUS_CHAMADO:
        raise ValueError("Selecione uma situação válida.")

    if previsao_termino < data_inicio:
        raise ValueError(
            "A previsão de término não pode ser anterior ao início."
        )

    cliente = obter_cliente_valido(cliente_id)

    if not cliente:
        raise ValueError(
            "O cliente selecionado não foi encontrado na sua conta."
        )

    funcionarios_ids = request.form.getlist("funcionarios_ids")
    equipe = obter_funcionarios_validos(funcionarios_ids)

    # Preserva a ordem dos funcionários selecionados e evita
    # aceitar IDs que não pertencem à conta.
    if len(equipe) != len(set(funcionarios_ids)):
        raise ValueError(
            "Um ou mais funcionários selecionados não são válidos."
        )

    try:
        valor_contratado = converter_valor(
            request.form.get("valor_contratado")
        )

        desconto = converter_valor(
            request.form.get("desconto")
        )

    except ValueError:
        raise

    if desconto > valor_contratado:
        raise ValueError(
            "O desconto não pode ser maior que o valor contratado."
        )

    valor_final = round(valor_contratado - desconto, 2)

    endereco = {
        "rua": request.form.get("rua", "").strip(),
        "numero": request.form.get("numero", "").strip(),
        "bairro": request.form.get("bairro", "").strip(),
        "cidade": request.form.get("cidade", "").strip(),
        "estado": request.form.get("estado", "").strip().upper(),
        "cep": request.form.get("cep", "").strip(),
        "complemento": request.form.get("complemento", "").strip()
    }

    responsavel_pagamento = (
        request.form.get("responsavel_pagamento", "").strip()
        or cliente.get("nome", "")
    )

    materiais_previstos, ferramentas_previstas = obter_associacoes_previstas()

    return {
        "materiais_previstos": materiais_previstos,
        "ferramentas_previstas": ferramentas_previstas,
        "titulo": titulo,
        "descricao": descricao,
        "cliente_id": str(cliente["_id"]),
        "cliente_nome": cliente.get("nome", ""),
        "cliente_telefone": cliente.get("telefone", ""),
        "cliente_email": cliente.get("email", ""),
        "responsavel_pagamento": responsavel_pagamento,
        "endereco": endereco,
        "prioridade": prioridade,
        "status": status,
        "data_inicio": data_inicio,
        "previsao_termino": previsao_termino,
        "valor_contratado": valor_contratado,
        "desconto": desconto,
        "valor_final": valor_final,
        "equipe_prevista": equipe,
        "observacoes": request.form.get("observacoes", "").strip()
    }


def preparar_chamado_para_template(chamado):
    chamado["data_inicio_input"] = data_para_input(
        chamado.get("data_inicio")
    )

    chamado["previsao_termino_input"] = data_para_input(
        chamado.get("previsao_termino")
    )

    endereco = chamado.get("endereco", {})

    partes_endereco = [
        endereco.get("rua", ""),
        endereco.get("numero", ""),
        endereco.get("bairro", ""),
        endereco.get("cidade", ""),
        endereco.get("estado", "")
    ]

    chamado["endereco_resumido"] = ", ".join(
        parte for parte in partes_endereco if parte
    )

    chamado["status_label"] = STATUS_CHAMADO.get(
        chamado.get("status"),
        "Não informado"
    )

    chamado["prioridade_label"] = PRIORIDADES.get(
        chamado.get("prioridade"),
        "Normal"
    )

    return chamado


# =========================================================
# LISTAGEM E FILTROS
# =========================================================

@chamados_bp.route("/chamados")
def listar_chamados():

    usuario_id = obter_usuario_id()

    if not usuario_id:
        return redirect(url_for("inicio"))

    db = get_database()
    colecao = db["chamados"]

    hoje = agora()
    competencia_atual = hoje.strftime("%Y-%m")

    busca = request.args.get("busca", "").strip()
    status = request.args.get("status", "").strip()
    prioridade = request.args.get("prioridade", "").strip()
    competencia = request.args.get(
        "competencia",
        competencia_atual
    ).strip()

    filtro = {
        "usuario_id": usuario_id,
        "arquivado": {"$ne": True},
        "excluido": {"$ne": True}
    }

    if competencia != "todos":
        filtro["competencia"] = competencia

    if status in STATUS_CHAMADO:
        filtro["status"] = status

    if prioridade in PRIORIDADES:
        filtro["prioridade"] = prioridade

    if busca:
        termo = re.escape(busca)

        filtro["$or"] = [
            {"numero": {"$regex": termo, "$options": "i"}},
            {"titulo": {"$regex": termo, "$options": "i"}},
            {"cliente_nome": {"$regex": termo, "$options": "i"}},
            {"responsavel_pagamento": {"$regex": termo, "$options": "i"}},
            {"endereco.rua": {"$regex": termo, "$options": "i"}},
            {"endereco.bairro": {"$regex": termo, "$options": "i"}}
        ]

    # Paginação da lista principal: 5 chamados por página.
    por_pagina = 5
    pagina = request.args.get("pagina", 1, type=int)
    pagina = max(pagina, 1)

    total_registros = colecao.count_documents(filtro)
    total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
    pagina = min(pagina, total_paginas)

    configuracao_usuario = db["configuracoes"].find_one(
        {"usuario_id": usuario_id}, {"preferencias.prioridade_chamados_primeiro": 1}
    ) or {}
    prioridade_primeira = configuracao_usuario.get("preferencias", {}).get(
        "prioridade_chamados_primeiro", "urgente"
    )
    ordem_prioridades = [prioridade_primeira] + [
        item for item in ["urgente", "alta", "normal", "baixa"]
        if item != prioridade_primeira
    ]

    pipeline_chamados = [
        {"$match": filtro},
        {"$addFields": {"_prioridade_ordem": {"$indexOfArray": [ordem_prioridades, "$prioridade"]}}},
        {"$sort": {"_prioridade_ordem": 1, "numero": -1, "criado_em": -1, "_id": -1}},
        {"$skip": (pagina - 1) * por_pagina},
        {"$limit": por_pagina},
        {"$project": {"_prioridade_ordem": 0}}
    ]
    chamados = list(colecao.aggregate(pipeline_chamados))

    chamados = [
        preparar_chamado_para_template(chamado)
        for chamado in chamados
    ]

    # Preserva os filtros ao navegar entre as páginas.
    argumentos_paginacao = request.args.to_dict()
    argumentos_paginacao.pop("pagina", None)

    filtro_base = {
        "usuario_id": usuario_id,
        "competencia": competencia_atual
    }

    total_mes = colecao.count_documents(filtro_base)

    em_andamento = colecao.count_documents({
        **filtro_base,
        "status": "em_andamento"
    })

    aguardando = colecao.count_documents({
        **filtro_base,
        "status": "aguardando"
    })

    concluidos = colecao.count_documents({
        **filtro_base,
        "status": "concluido"
    })

    total_valor = list(
        colecao.aggregate([
            {
                "$match": {
                    **filtro_base,
                    "excluido": {"$ne": True}
                }
            },
            {
                "$group": {
                    "_id": None,
                    "valor": {"$sum": "$valor_final"}
                }
            }
        ])
    )

    valor_contratado_mes = (
        total_valor[0]["valor"]
        if total_valor else 0
    )

    meses = obter_meses_disponiveis(colecao, usuario_id)

    if competencia_atual not in meses:
        meses.insert(0, competencia_atual)

    meses_formatados = [
        {
            "valor": mes,
            "nome": formatar_competencia(mes)
        }
        for mes in meses
    ]

    return render_template(
        "chamados.html",
        chamados=chamados,
        clientes=carregar_clientes(),
        funcionarios=carregar_funcionarios(),
        materiais=carregar_materiais_disponiveis(),
        ferramentas=carregar_ferramentas_disponiveis(),
        busca=busca,
        status_filtro=status,
        prioridade_filtro=prioridade,
        competencia=competencia,
        competencia_atual=competencia_atual,
        meses=meses_formatados,
        total_mes=total_mes,
        em_andamento=em_andamento,
        aguardando=aguardando,
        concluidos=concluidos,
        valor_contratado_mes=valor_contratado_mes,
        status_opcoes=STATUS_CHAMADO,
        prioridades=PRIORIDADES,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        argumentos_paginacao=argumentos_paginacao,
        chamado_edicao=None
    )


# =========================================================
# CADASTRO
# =========================================================

@chamados_bp.route("/chamados/novo", methods=["POST"])
def cadastrar_chamado():

    if not obter_usuario_id():
        return redirect(url_for("inicio"))

    try:
        dados = preparar_dados_formulario()

    except ValueError as erro:
        flash(str(erro), "danger")
        return voltar_para_lista()

    db = get_database()
    colecao = db["chamados"]

    ano = agora().strftime("%Y")
    numero_sequencial = colecao.count_documents({
        "usuario_id": obter_usuario_id(),
        "ano_numero": ano
    }) + 1

    numero = f"TB-{ano}-{numero_sequencial:05d}"

    data_criacao = agora()

    chamado = {
        "usuario_id": obter_usuario_id(),
        "numero": numero,
        "ano_numero": ano,

        "competencia": data_criacao.strftime("%Y-%m"),

        **dados,

        "valor_recebido": 0.0,
        "saldo_pendente": dados["valor_final"],

        "ciclos": [],
        "historico": [
            {
                "acao": "criado",
                "descricao": "Chamado cadastrado.",
                "data": data_criacao,
                "usuario_nome": session.get("usuario_nome", "Usuário")
            }
        ],

        "arquivado": False,
        "excluido": False,

        "criado_em": data_criacao,
        "atualizado_em": data_criacao
    }

    try:
        colecao.insert_one(chamado)

        flash(
            f"Chamado {numero} cadastrado com sucesso!",
            "success"
        )

    except Exception:
        current_app.logger.exception("Erro ao cadastrar chamado.")
        flash("Não foi possível cadastrar o chamado.", "danger")

    return voltar_para_lista()


# =========================================================
# EDIÇÃO
# =========================================================

@chamados_bp.route("/chamados/<chamado_id>/editar")
def editar_chamado(chamado_id):

    chamado = buscar_chamado(chamado_id)

    if not chamado:
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()

    if chamado.get("arquivado") or chamado.get("excluido"):
        flash(
            "Chamados arquivados ou excluídos não podem ser editados "
            "por esta tela.",
            "warning"
        )
        return voltar_para_lista()

    chamado = preparar_chamado_para_template(chamado)

    return render_template(
        "chamados.html",
        chamados=[],
        clientes=carregar_clientes(),
        funcionarios=carregar_funcionarios(),
        materiais=carregar_materiais_disponiveis(),
        ferramentas=carregar_ferramentas_disponiveis(chamado),
        busca="",
        status_filtro="",
        prioridade_filtro="",
        competencia=chamado.get("competencia"),
        competencia_atual=agora().strftime("%Y-%m"),
        meses=[],
        total_mes=0,
        em_andamento=0,
        aguardando=0,
        concluidos=0,
        valor_contratado_mes=0,
        status_opcoes=STATUS_CHAMADO,
        prioridades=PRIORIDADES,
        pagina=1,
        total_paginas=1,
        total_registros=0,
        argumentos_paginacao={},
        chamado_edicao=chamado
    )


@chamados_bp.route(
    "/chamados/<chamado_id>/atualizar",
    methods=["POST"]
)
def atualizar_chamado(chamado_id):

    chamado = buscar_chamado(chamado_id)

    if not chamado:
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()

    if chamado.get("arquivado") or chamado.get("excluido"):
        flash("Este chamado não pode ser editado.", "warning")
        return voltar_para_lista()

    try:
        dados = preparar_dados_formulario()

    except ValueError as erro:
        flash(str(erro), "danger")
        return redirect(
            url_for(
                "chamados.editar_chamado",
                chamado_id=chamado_id
            )
        )

    dados["atualizado_em"] = agora()

    dados["saldo_pendente"] = max(
        round(
            dados["valor_final"] - chamado.get("valor_recebido", 0),
            2
        ),
        0
    )

    registro_historico = {
        "acao": "editado",
        "descricao": "Dados principais do chamado atualizados.",
        "data": agora(),
        "usuario_nome": session.get("usuario_nome", "Usuário")
    }

    try:
        get_database()["chamados"].update_one(
            {
                "_id": ObjectId(chamado_id),
                "usuario_id": obter_usuario_id()
            },
            {
                "$set": dados,
                "$push": {
                    "historico": registro_historico
                }
            }
        )

        flash("Chamado atualizado com sucesso!", "success")

    except Exception:
        current_app.logger.exception("Erro ao atualizar chamado.")
        flash("Não foi possível atualizar o chamado.", "danger")

    return voltar_para_lista()


# =========================================================
# ATUALIZAÇÃO DE SITUAÇÃO
# =========================================================

@chamados_bp.route(
    "/chamados/<chamado_id>/situacao",
    methods=["POST"]
)
def atualizar_situacao(chamado_id):

    chamado = buscar_chamado(chamado_id)

    if not chamado:
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()

    if chamado.get("arquivado") or chamado.get("excluido"):
        flash("Este chamado não pode ter a situação alterada.", "warning")
        return voltar_para_lista()

    novo_status = request.form.get("status", "").strip()

    if novo_status not in STATUS_CHAMADO:
        flash("Situação inválida.", "danger")
        return voltar_para_lista()

    data_atual = agora()

    atualizacoes = {
        "status": novo_status,
        "atualizado_em": data_atual
    }

    if novo_status == "concluido":
        atualizacoes["data_conclusao"] = data_atual

    else:
        atualizacoes["data_conclusao"] = None

    registro_historico = {
        "acao": "situacao_alterada",
        "descricao": (
            f"Situação alterada para {STATUS_CHAMADO[novo_status]}."
        ),
        "data": data_atual,
        "usuario_nome": session.get("usuario_nome", "Usuário")
    }

    try:
        get_database()["chamados"].update_one(
            {
                "_id": ObjectId(chamado_id),
                "usuario_id": obter_usuario_id()
            },
            {
                "$set": atualizacoes,
                "$push": {
                    "historico": registro_historico
                }
            }
        )

        flash("Situação do chamado atualizada.", "success")

    except Exception:
        current_app.logger.exception(
            "Erro ao atualizar situação do chamado."
        )
        flash("Não foi possível atualizar a situação.", "danger")

    return voltar_para_lista()


# =========================================================
# CALENDÁRIO: EVENTOS DAS OBRAS
# =========================================================

@chamados_bp.route("/chamados/eventos")
def eventos_calendario():

    usuario_id = obter_usuario_id()

    if not usuario_id:
        return {"erro": "Sessão expirada."}, 401

    inicio_periodo = request.args.get("start", "")
    fim_periodo = request.args.get("end", "")

    try:
        inicio = datetime.fromisoformat(
            inicio_periodo.replace("Z", "+00:00")
        )

        fim = datetime.fromisoformat(
            fim_periodo.replace("Z", "+00:00")
        )

    except (ValueError, TypeError):
        return {"erro": "Período inválido."}, 400

    filtro = {
        "usuario_id": usuario_id,
        "arquivado": {"$ne": True},
        "excluido": {"$ne": True},
        "data_inicio": {"$lt": fim},
        "previsao_termino": {"$gte": inicio}
    }

    chamados = list(
        get_database()["chamados"].find(
            filtro,
            {
                "numero": 1,
                "titulo": 1,
                "cliente_nome": 1,
                "status": 1,
                "prioridade": 1,
                "data_inicio": 1,
                "previsao_termino": 1,
                "endereco": 1,
                "valor_final": 1
            }
        )
    )

    cores_status = {
        "a_iniciar": "#8B83A4",
        "em_andamento": "#4F83C2",
        "aguardando": "#D69A42",
        "concluido": "#4D9A75"
    }

    eventos = []

    for chamado in chamados:

        data_inicio = chamado.get("data_inicio")
        previsao = chamado.get("previsao_termino")

        if not data_inicio or not previsao:
            continue

        # FullCalendar utiliza data final exclusiva em eventos
        # de dia inteiro. Somamos um dia para incluir a previsão.
        data_fim_exclusiva = (
        previsao.date() + timedelta(days=1)
        )

        endereco = chamado.get("endereco", {})

        endereco_texto = ", ".join(
            parte for parte in [
                endereco.get("rua", ""),
                endereco.get("numero", ""),
                endereco.get("bairro", ""),
                endereco.get("cidade", "")
            ] if parte
        )

        status = chamado.get("status", "a_iniciar")

        eventos.append({
            "id": str(chamado["_id"]),
            "title": chamado.get("titulo", "Obra sem título"),
            "start": data_inicio.strftime("%Y-%m-%d"),
            "end": data_fim_exclusiva.strftime("%Y-%m-%d"),
            "allDay": True,
            "url": url_for(
                "chamados.visualizar_chamado",
                chamado_id=str(chamado["_id"])
            ),
            "backgroundColor": cores_status.get(
                status,
                "#8B83A4"
            ),
            "borderColor": cores_status.get(
                status,
                "#8B83A4"
            ),
            "extendedProps": {
                "numero": chamado.get("numero", ""),
                "cliente": chamado.get("cliente_nome", ""),
                "status": STATUS_CHAMADO.get(status, "Não informado"),
                "prioridade": PRIORIDADES.get(
                    chamado.get("prioridade"),
                    "Normal"
                ),
                "endereco": endereco_texto,
                "valor": chamado.get("valor_final", 0)
            }
        })

    return eventos_calendario_json(eventos)


def eventos_calendario_json(eventos):
    from flask import jsonify
    return jsonify(eventos)


# =========================================================
# VISUALIZAÇÃO, ARQUIVO, LIXEIRA E RESTAURAÇÃO
# =========================================================

@chamados_bp.route("/chamados/<chamado_id>")
def visualizar_chamado(chamado_id):
    chamado = buscar_chamado(chamado_id)
    if not chamado or chamado.get("excluido"):
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()
    chamado = preparar_chamado_para_template(chamado)
    return render_template("chamado_detalhes.html", chamado=chamado, status_opcoes=STATUS_CHAMADO, prioridades=PRIORIDADES)


def registrar_acao_chamado(chamado_id, campo, valor, acao, descricao):
    chamado = buscar_chamado(chamado_id)
    if not chamado:
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()
    data = agora()
    get_database()["chamados"].update_one(
        {"_id": chamado["_id"], "usuario_id": obter_usuario_id()},
        {"$set": {campo: valor, "atualizado_em": data}, "$push": {"historico": {
            "acao": acao, "descricao": descricao, "data": data,
            "usuario_nome": session.get("usuario_nome", "Usuário")
        }}}
    )
    flash(descricao, "success")
    return voltar_para_lista()


@chamados_bp.route("/chamados/<chamado_id>/arquivar", methods=["POST"])
def arquivar_chamado(chamado_id):
    chamado = buscar_chamado(chamado_id)

    if not chamado or chamado.get("excluido"):
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()

    if chamado.get("arquivado"):
        flash("Este chamado já está arquivado.", "warning")
        return voltar_para_lista()

    data = agora()

    db = get_database()

    db["chamados"].update_one(
        {
            "_id": chamado["_id"],
            "usuario_id": obter_usuario_id()
        },
        {
            "$set": {
                "arquivado": True,
                "arquivado_em": data,
                "atualizado_em": data
            },
            "$push": {
                "historico": {
                    "acao": "arquivado",
                    "descricao": "Chamado arquivado. O histórico foi preservado.",
                    "data": data,
                    "usuario_nome": session.get("usuario_nome", "Usuário")
                }
            }
        }
    )

    flash("Chamado arquivado com sucesso.", "success")
    return voltar_para_lista()


@chamados_bp.route("/chamados/<chamado_id>/excluir", methods=["POST"])
def enviar_para_lixeira(chamado_id):
    chamado = buscar_chamado(chamado_id)

    if not chamado or chamado.get("excluido"):
        flash("Chamado não encontrado.", "danger")
        return voltar_para_lista()

    data = agora()

    db = get_database()

    db["chamados"].update_one(
        {
            "_id": chamado["_id"],
            "usuario_id": obter_usuario_id()
        },
        {
            "$set": {
                "excluido": True,
                "excluido_em": data,
                "atualizado_em": data
            },
            "$push": {
                "historico": {
                    "acao": "enviado_lixeira",
                    "descricao": "Chamado enviado para a lixeira.",
                    "data": data,
                    "usuario_nome": session.get("usuario_nome", "Usuário")
                }
            }
        }
    )

    flash("Chamado enviado para a lixeira.", "success")
    return voltar_para_lista()


@chamados_bp.route("/chamados/arquivados")
def listar_arquivados():

    usuario_id = obter_usuario_id()
    if not usuario_id:
        return redirect(url_for("inicio"))

    colecao = get_database()["chamados"]
    filtro = {
        "usuario_id": usuario_id,
        "arquivado": True,
        "excluido": {"$ne": True}
    }

    # Arquivados: 25 registros por página.
    por_pagina = 25
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    total_registros = colecao.count_documents(filtro)
    total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
    pagina = min(pagina, total_paginas)

    itens = list(
        colecao.find(filtro)
        .sort([
            ("numero", -1),
            ("criado_em", -1),
            ("_id", -1)
        ])
        .skip((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )

    return render_template(
        "chamados_arquivados.html",
        chamados=[
            preparar_chamado_para_template(item)
            for item in itens
        ],
        titulo_lista="Chamados arquivados",
        lixeira=False,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros
    )


@chamados_bp.route("/chamados/lixeira")
def listar_lixeira():

    usuario_id = obter_usuario_id()
    if not usuario_id:
        return redirect(url_for("inicio"))

    colecao = get_database()["chamados"]
    filtro = {
        "usuario_id": usuario_id,
        "excluido": True
    }

    # Lixeira: 25 registros por página.
    por_pagina = 25
    pagina = max(request.args.get("pagina", 1, type=int), 1)
    total_registros = colecao.count_documents(filtro)
    total_paginas = max(1, (total_registros + por_pagina - 1) // por_pagina)
    pagina = min(pagina, total_paginas)

    itens = list(
        colecao.find(filtro)
        .sort([
            ("numero", -1),
            ("criado_em", -1),
            ("_id", -1)
        ])
        .skip((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )

    return render_template(
        "chamados_arquivados.html",
        chamados=[
            preparar_chamado_para_template(item)
            for item in itens
        ],
        titulo_lista="Lixeira de chamados",
        lixeira=True,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros
    )

@chamados_bp.route("/chamados/<chamado_id>/restaurar", methods=["POST"])
def restaurar_chamado(chamado_id):

    chamado = buscar_chamado(chamado_id)

    if not chamado or (
        not chamado.get("excluido")
        and not chamado.get("arquivado")
    ):
        flash("Chamado não encontrado na área de recuperação.", "danger")
        return voltar_para_lista()

    data = agora()

    get_database()["chamados"].update_one(
        {
            "_id": chamado["_id"],
            "usuario_id": obter_usuario_id()
        },
        {
            "$set": {
                "excluido": False,
                "arquivado": False,
                "arquivado_em": None,
                "excluido_em": None,
                "atualizado_em": data
            },
            "$push": {
                "historico": {
                    "acao": "restaurado",
                    "descricao": "Chamado restaurado para a lista ativa.",
                    "data": data,
                    "usuario_nome": session.get("usuario_nome", "Usuário")
                }
            }
        }
    )

    flash("Chamado restaurado com sucesso.", "success")
    return voltar_para_lista()

@chamados_bp.route("/chamados/<chamado_id>/excluir-permanentemente", methods=["POST"])
def excluir_permanentemente(chamado_id):
    chamado = buscar_chamado(chamado_id)
    if not chamado or not chamado.get("excluido"):
        flash("Somente chamados na lixeira podem ser excluídos permanentemente.", "warning")
        return redirect(url_for("chamados.listar_lixeira"))
    get_database()["chamados"].delete_one({"_id": chamado["_id"], "usuario_id": obter_usuario_id(), "excluido": True})
    flash("Chamado excluído permanentemente.", "success")
    return redirect(url_for("chamados.listar_lixeira"))