from datetime import datetime, timezone
import calendar
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import StringIO
import csv
import re

from bson import ObjectId
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    current_app
)

from app.database.connection import get_database
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from app.services.financeiro_service import (
    preparar_movimentacao,
    sincronizar_compras_estoque,
    atualizar_totais_chamado,
    sincronizar_aquisicoes_ferramentas,
    obter_competencia,
    obter_dia_fechamento
)

financeiro_bp = Blueprint("financeiro", __name__)

CATEGORIAS_ENTRADA = {
    "pagamento_obra": "Pagamento de obra",
    "servico": "Serviços",
    "venda": "Vendas",
    "outros_recebimentos": "Outros recebimentos"
}
CATEGORIAS_SAIDA = {
    "materiais": "Materiais",
    "funcionarios": "Funcionários",
    "ferramentas": "Ferramentas e manutenção",
    "transporte": "Transporte",
    "alimentacao": "Alimentação",
    "impostos": "Impostos e taxas",
    "contas": "Contas fixas",
    "servicos_terceiros": "Serviços de terceiros",
    "outros_gastos": "Outras despesas"
}
FORMAS_PAGAMENTO = {
    "dinheiro": "Dinheiro",
    "pix": "PIX",
    "credito": "Cartão de crédito",
    "debito": "Cartão de débito",
    "transferencia": "Transferência",
    "boleto": "Boleto",
    "cheque": "Cheque",
    "nao_informado": "Não informado"
}
STATUS_MOVIMENTO = {
    "realizado": "Realizado",
    "pendente": "Pendente"
}
ITENS_POR_PAGINA = 20



def montar_analise_graficos(db, usuario, competencia):
    """Monta indicadores de resultado agrupados pelo mês real da movimentação."""
    try:
        ano_ref, mes_ref = map(int, competencia.split("-"))
    except (TypeError, ValueError):
        hoje = agora()
        ano_ref, mes_ref = hoje.year, hoje.month

    meses = []
    ano, mes = ano_ref, mes_ref
    for _ in range(12):
        meses.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1
    meses.reverse()

    totais = {item: {"entrada": 0.0, "saida": 0.0} for item in meses}
    despesas_categoria = {}
    primeiro = meses[0]
    inicio_analise = datetime(int(primeiro[:4]), int(primeiro[5:7]), 1, tzinfo=timezone.utc)
    proximo_ano, proximo_mes = ano_ref, mes_ref + 1
    if proximo_mes > 12:
        proximo_mes = 1
        proximo_ano += 1
    fim_analise = datetime(proximo_ano, proximo_mes, 1, tzinfo=timezone.utc)

    cursor = db["movimentacoes_financeiras"].find({
        "usuario_id": usuario,
        "data_movimento": {"$gte": inicio_analise, "$lt": fim_analise},
        "status": "realizado",
        "cancelada": {"$ne": True}
    }, {"data_movimento": 1, "tipo": 1, "valor": 1, "categoria": 1})
    for movimento in cursor:
        data_mov = movimento.get("data_movimento")
        if not isinstance(data_mov, datetime):
            continue
        comp = f"{data_mov.year:04d}-{data_mov.month:02d}"
        if comp not in totais:
            continue
        try:
            valor = float(movimento.get("valor", 0) or 0)
        except (TypeError, ValueError):
            valor = 0.0
        if movimento.get("tipo") == "entrada":
            totais[comp]["entrada"] += valor
        elif movimento.get("tipo") == "saida":
            totais[comp]["saida"] += valor
            categoria = movimento.get("categoria") or "outros_gastos"
            despesas_categoria[categoria] = despesas_categoria.get(categoria, 0.0) + valor

    nomes_meses = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
    labels = [f"{nomes_meses[int(item[5:7]) - 1]}/{item[2:4]}" for item in meses]
    entradas = [round(totais[item]["entrada"], 2) for item in meses]
    saidas = [round(totais[item]["saida"], 2) for item in meses]
    resultados = [round(totais[item]["entrada"] - totais[item]["saida"], 2) for item in meses]
    total_entradas = round(sum(entradas), 2)
    total_saidas = round(sum(saidas), 2)
    resultado_acumulado = round(total_entradas - total_saidas, 2)
    margem = round((resultado_acumulado / total_entradas) * 100, 1) if total_entradas else 0.0
    meses_com_prejuizo = sum(1 for valor in resultados if valor < 0)
    meses_com_lucro = sum(1 for valor in resultados if valor > 0)

    fig_tendencia = go.Figure()
    fig_tendencia.add_trace(go.Scatter(
        name="Entradas", x=labels, y=entradas, mode="lines+markers",
        line=dict(color="#9B78D0", width=3), marker=dict(size=6),
        hovertemplate="Entradas: R$ %{y:,.2f}<extra></extra>"
    ))
    fig_tendencia.add_trace(go.Scatter(
        name="Despesas", x=labels, y=saidas, mode="lines+markers",
        line=dict(color="#E6A2C5", width=3), marker=dict(size=6),
        hovertemplate="Despesas: R$ %{y:,.2f}<extra></extra>"
    ))
    fig_tendencia.update_layout(
        height=310, margin=dict(l=12, r=12, t=20, b=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Nunito Sans, sans-serif", color="#82758F", size=11),
        legend=dict(orientation="h", y=1.16, x=0),
        xaxis=dict(showgrid=False, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="rgba(150,130,170,.13)", tickprefix="R$ ", tickformat="~s", fixedrange=True),
        hovermode="x unified"
    )

    cores_resultado = ["#65B895" if valor >= 0 else "#D97991" for valor in resultados]
    fig_resultado = go.Figure(go.Bar(
        x=labels, y=resultados,
        marker_color=cores_resultado,
        hovertemplate="Resultado: R$ %{y:,.2f}<extra></extra>"
    ))
    fig_resultado.add_hline(y=0, line_color="#9A8AA8", line_width=1)
    fig_resultado.update_layout(
        height=285, margin=dict(l=12, r=12, t=20, b=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Nunito Sans, sans-serif", color="#82758F", size=11),
        showlegend=False, xaxis=dict(showgrid=False, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="rgba(150,130,170,.13)", tickprefix="R$ ", tickformat="~s", fixedrange=True)
    )

    categorias_nomes = {
        "materiais": "Materiais", "funcionarios": "Funcionários",
        "ferramentas": "Ferramentas e manutenção", "transporte": "Transporte",
        "alimentacao": "Alimentação", "impostos": "Impostos e taxas",
        "contas": "Contas fixas", "servicos_terceiros": "Serviços de terceiros",
        "outros_gastos": "Outras despesas"
    }
    categorias_ordenadas = sorted(despesas_categoria.items(), key=lambda item: item[1], reverse=True)
    fig_categorias = go.Figure(go.Pie(
        labels=[categorias_nomes.get(chave, chave.replace("_", " ").title()) for chave, _ in categorias_ordenadas],
        values=[round(valor, 2) for _, valor in categorias_ordenadas],
        hole=.62, sort=False,
        marker=dict(colors=["#9B78D0", "#E6A2C5", "#78B8A5", "#E7B96F", "#8CAED6", "#B8A9C9", "#C58DB8", "#7C9B9A", "#A9A0D0"]),
        textinfo="percent", hovertemplate="%{label}: R$ %{value:,.2f} (%{percent})<extra></extra>"
    ))
    fig_categorias.update_layout(
        height=285, margin=dict(l=8, r=8, t=14, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Nunito Sans, sans-serif", color="#82758F", size=10),
        legend=dict(orientation="h", y=-.12, x=.5, xanchor="center")
    )

    return {
        "grafico_tendencia": json.dumps(fig_tendencia, cls=PlotlyJSONEncoder),
        "grafico_resultado": json.dumps(fig_resultado, cls=PlotlyJSONEncoder),
        "grafico_categorias": json.dumps(fig_categorias, cls=PlotlyJSONEncoder),
        "analise": {
            "total_entradas_12m": total_entradas,
            "total_saidas_12m": total_saidas,
            "resultado_12m": resultado_acumulado,
            "margem_12m": margem,
            "meses_lucro": meses_com_lucro,
            "meses_prejuizo": meses_com_prejuizo
        }
    }


def usuario_id():
    return session.get("usuario_id")


def agora():
    return datetime.now(timezone.utc)


def converter_valor(texto):
    valor = str(texto or "").strip().replace("R$", "").replace(" ", "")
    if not valor:
        raise InvalidOperation
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    numero = Decimal(valor)
    if not numero.is_finite() or numero <= 0:
        raise InvalidOperation
    return float(numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def converter_data(texto):
    if not texto:
        return agora()
    return datetime.strptime(texto, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def buscar_por_id(colecao, identificador, usuario):
    if not identificador:
        return None
    if not ObjectId.is_valid(identificador):
        return None
    return colecao.find_one({
        "_id": ObjectId(identificador),
        "usuario_id": usuario
    })


def obter_periodo_padrao(db, usuario):
    hoje = agora()
    config = db["configuracoes"].find_one(
        {"usuario_id": usuario}, {"dia_fechamento": 1}
    ) or {}
    fechamento = max(1, min(int(config.get("dia_fechamento", 30) or 30), 31))
    mes = hoje.month + (1 if hoje.day > fechamento else 0)
    ano = hoje.year
    if mes > 12:
        mes = 1
        ano += 1
    return f"{ano:04d}-{mes:02d}"


def carregar_opcoes(db, usuario):
    chamados = list(db["chamados"].find({
        "usuario_id": usuario,
        "excluido": {"$ne": True}
    }, {
        "numero": 1, "titulo": 1, "cliente_nome": 1,
        "valor_final": 1, "valor_recebido": 1, "saldo_pendente": 1
    }).sort("criado_em", -1).limit(300))

    clientes = list(db["clientes"].find({
        "usuario_id": usuario,
        "excluido": {"$ne": True}
    }, {"nome": 1}).sort("nome", 1).limit(500))

    funcionarios = list(db["funcionarios"].find({
        "usuario_id": usuario,
        "situacao": {"$ne": "desligado"}
    }, {"nome": 1, "cargo": 1}).sort("nome", 1).limit(300))

    return chamados, clientes, funcionarios


def montar_filtro(usuario, competencia="", tipo="", status=""):
    # A listagem mantém cancelamentos no histórico; os totais os excluem.
    filtro = {"usuario_id": usuario}
    if competencia:
        filtro["competencia"] = competencia
    if tipo in ("entrada", "saida"):
        filtro["tipo"] = tipo
    if status in STATUS_MOVIMENTO:
        filtro["status"] = status
    return filtro


def somar_movimentos(db, filtro):
    filtro_totais = {**filtro, "cancelada": {"$ne": True}}
    pipeline = [
        {"$match": filtro_totais},
        {"$group": {
            "_id": {"tipo": "$tipo", "status": "$status"},
            "total": {"$sum": "$valor"},
            "quantidade": {"$sum": 1}
        }}
    ]
    resultado = list(db["movimentacoes_financeiras"].aggregate(pipeline))
    totais = {
        "entradas": 0.0, "saidas": 0.0,
        "entradas_pendentes": 0.0, "saidas_pendentes": 0.0,
        "a_receber": 0.0
    }
    for item in resultado:
        tipo_mov = item["_id"].get("tipo")
        status_mov = item["_id"].get("status")
        chave = (
            "entradas" if tipo_mov == "entrada" else "saidas"
        ) if status_mov == "realizado" else (
            "entradas_pendentes" if tipo_mov == "entrada" else "saidas_pendentes"
        )
        totais[chave] += float(item.get("total", 0) or 0)
    totais["saldo"] = round(totais["entradas"] - totais["saidas"], 2)
    return {k: round(v, 2) for k, v in totais.items()}


def paginar_registros(colecao, filtro, pagina, por_pagina=10, ordenacao=None):
    total = colecao.count_documents(filtro)
    paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina = min(max(1, pagina), paginas)
    cursor = colecao.find(filtro)
    if ordenacao:
        cursor = cursor.sort(ordenacao)
    itens = list(cursor.skip((pagina - 1) * por_pagina).limit(por_pagina))
    return itens, pagina, paginas, total


@financeiro_bp.route("/financeiro")
def index():
    usuario = usuario_id()
    if not usuario:
        return redirect(url_for("inicio"))

    db = get_database()
    try:
        db["movimentacoes_financeiras"].create_index(
            [("usuario_id", 1), ("competencia", 1), ("data_movimento", -1)]
        )
        db["movimentacoes_financeiras"].create_index(
            [("usuario_id", 1), ("chamado_id", 1), ("tipo", 1), ("status", 1)]
        )
        db["movimentacoes_financeiras"].create_index(
            [("usuario_id", 1), ("origem_movimentacao_estoque_id", 1)]
        )
        sincronizar_compras_estoque(db, usuario)
        sincronizar_aquisicoes_ferramentas(db, usuario)
    except Exception:
        current_app.logger.exception("Não foi possível sincronizar compras antigas do estoque.")

    competencia = request.args.get("competencia", "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", competencia or ""):
        competencia = obter_periodo_padrao(db, usuario)

    tipo = request.args.get("tipo", "").strip()
    status = request.args.get("status", "").strip()
    busca = request.args.get("busca", "").strip()

    filtro = montar_filtro(usuario, competencia, tipo, status)
    if busca:
        termo = re.escape(busca)
        filtro["$or"] = [
            {"descricao": {"$regex": termo, "$options": "i"}},
            {"cliente_nome": {"$regex": termo, "$options": "i"}},
            {"chamado_numero": {"$regex": termo, "$options": "i"}},
            {"fornecedor": {"$regex": termo, "$options": "i"}},
            {"funcionario_nome": {"$regex": termo, "$options": "i"}}
        ]

    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    total_registros = db["movimentacoes_financeiras"].count_documents(filtro)
    total_paginas = max(1, (total_registros + ITENS_POR_PAGINA - 1) // ITENS_POR_PAGINA)
    pagina = min(pagina, total_paginas)

    movimentos = list(
        db["movimentacoes_financeiras"].find(filtro)
        .sort([("data_movimento", -1), ("criado_em", -1)])
        .skip((pagina - 1) * ITENS_POR_PAGINA)
        .limit(ITENS_POR_PAGINA)
    )

    # Pendências são exibidas à parte e não entram no saldo de caixa.
    filtro_competencia = {"usuario_id": usuario, "competencia": competencia, "cancelada": {"$ne": True}}
    totais_competencia = somar_movimentos(db, filtro_competencia)

    # Pendências detalhadas para conferência rápida (10 por página).
    try:
        pendentes_pagina = max(1, int(request.args.get("pendentes_pagina", 1)))
        receber_pagina = max(1, int(request.args.get("receber_pagina", 1)))
    except (TypeError, ValueError):
        pendentes_pagina = receber_pagina = 1

    filtro_pendentes = {
        "usuario_id": usuario, "competencia": competencia,
        "status": "pendente", "cancelada": {"$ne": True}
    }
    pendentes_itens, pendentes_pagina, pendentes_total_paginas, pendentes_total = paginar_registros(
        db["movimentacoes_financeiras"], filtro_pendentes, pendentes_pagina,
        10, [("data_movimento", -1), ("criado_em", -1)]
    )

    todos_chamados_receber = list(db["chamados"].find({
        "usuario_id": usuario, "arquivado": {"$ne": True},
        "excluido": {"$ne": True}, "status": {"$ne": "cancelado"}
    }, {"numero": 1, "titulo": 1, "cliente_nome": 1, "valor_final": 1, "valor_recebido": 1, "saldo_pendente": 1, "status": 1, "previsao_termino": 1, "criado_em": 1}))
    obras_a_receber = []
    for item in todos_chamados_receber:
        saldo = max(float(item.get(
            "saldo_pendente",
            float(item.get("valor_final", 0) or 0) - float(item.get("valor_recebido", 0) or 0)
        ) or 0), 0)
        if saldo > 0:
            item["saldo_modal"] = round(saldo, 2)
            obras_a_receber.append(item)
    obras_a_receber.sort(key=lambda item: (
        str(item.get("previsao_termino") or ""),
        str(item.get("criado_em") or "")
    ))
    receber_total = len(obras_a_receber)
    receber_total_paginas = max(1, (receber_total + 9) // 10)
    receber_pagina = min(max(1, receber_pagina), receber_total_paginas)
    receber_itens = obras_a_receber[(receber_pagina - 1) * 10:receber_pagina * 10]
    totais_competencia["a_receber"] = round(sum(item["saldo_modal"] for item in obras_a_receber), 2)


    chamados, clientes, funcionarios = carregar_opcoes(db, usuario)
    analise_graficos = montar_analise_graficos(db, usuario, competencia)
    config_usuario = db["configuracoes"].find_one(
        {"usuario_id": usuario}, {"preferencias.permitir_baixar_graficos": 1}
    ) or {}
    permitir_baixar_graficos = config_usuario.get("preferencias", {}).get("permitir_baixar_graficos", True)

    # Painel de contas a receber: saldo pendente das obras, sem tratar
    # o valor contratado como receita recebida.
    obras_com_saldo = []
    for chamado in chamados:
        valor_final = float(chamado.get("valor_final", 0) or 0)
        valor_recebido = float(chamado.get("valor_recebido", 0) or 0)
        saldo_obra = float(
            chamado.get("saldo_pendente", max(valor_final - valor_recebido, 0))
            or 0
        )
        if saldo_obra > 0:
            chamado["saldo_calculado_financeiro"] = round(saldo_obra, 2)
            chamado["valor_final_financeiro"] = round(valor_final, 2)
            chamado["valor_recebido_financeiro"] = round(valor_recebido, 2)
            obras_com_saldo.append(chamado)

    return render_template(
        "financeiro.html",
        movimentos=movimentos,
        competencia=competencia,
        tipo_filtro=tipo,
        status_filtro=status,
        busca=busca,
        pagina=pagina,
        total_paginas=total_paginas,
        total_registros=total_registros,
        totais=totais_competencia,
        pendentes_itens=pendentes_itens,
        pendentes_pagina=pendentes_pagina,
        pendentes_total_paginas=pendentes_total_paginas,
        pendentes_total=pendentes_total,
        receber_itens=receber_itens,
        receber_pagina=receber_pagina,
        receber_total_paginas=receber_total_paginas,
        receber_total=receber_total,
        permitir_baixar_graficos=permitir_baixar_graficos,
        chamados=chamados,
        obras_com_saldo=obras_com_saldo,
        clientes=clientes,
        funcionarios=funcionarios,
        categorias_entrada=CATEGORIAS_ENTRADA,
        categorias_saida=CATEGORIAS_SAIDA,
        formas_pagamento=FORMAS_PAGAMENTO,
        status_movimento=STATUS_MOVIMENTO,
        **analise_graficos,
        now_date=agora().strftime("%Y-%m-%d")
    )




@financeiro_bp.route("/financeiro/exportar")
def exportar_csv():
    usuario = usuario_id()
    if not usuario:
        return redirect(url_for("inicio"))

    db = get_database()
    competencia = request.args.get("competencia", "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", competencia or ""):
        competencia = obter_periodo_padrao(db, usuario)

    filtro = montar_filtro(
        usuario,
        competencia,
        request.args.get("tipo", ""),
        request.args.get("status", "")
    )
    movimentos = db["movimentacoes_financeiras"].find(filtro).sort(
        [("data_movimento", -1), ("criado_em", -1)]
    )

    arquivo = StringIO()
    escritor = csv.writer(arquivo, delimiter=";")
    escritor.writerow([
        "Data", "Vencimento", "Competência", "Tipo", "Categoria", "Descrição",
        "Valor", "Situação", "Forma de pagamento", "Obra",
        "Cliente", "Funcionário", "Fornecedor", "Observações", "Cancelada"
    ])

    for item in movimentos:
        escritor.writerow([
            item.get("data_movimento").strftime("%d/%m/%Y") if item.get("data_movimento") else "",
            item.get("data_vencimento").strftime("%d/%m/%Y") if item.get("data_vencimento") else "",
            item.get("competencia", ""),
            item.get("tipo", ""),
            (CATEGORIAS_ENTRADA if item.get("tipo") == "entrada" else CATEGORIAS_SAIDA).get(item.get("categoria"), item.get("categoria", "")),
            item.get("descricao", ""),
            f'{float(item.get("valor", 0)):.2f}'.replace(".", ","),
            item.get("status", ""),
            FORMAS_PAGAMENTO.get(item.get("forma_pagamento"), item.get("forma_pagamento", "")),
            item.get("chamado_numero", ""),
            item.get("cliente_nome", ""),
            item.get("funcionario_nome", ""),
            item.get("fornecedor", ""),
            item.get("observacoes", ""),
            "Sim" if item.get("cancelada") else "Não"
        ])

    from flask import Response
    conteudo = "\ufeff" + arquivo.getvalue()
    nome = f"taskberry-financeiro-{competencia}.csv"
    return Response(
        conteudo,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'}
    )


@financeiro_bp.route("/financeiro/lancamentos", methods=["POST"])
def criar_movimentacao():
    usuario = usuario_id()
    if not usuario:
        return redirect(url_for("inicio"))

    tipo = request.form.get("tipo", "").strip()
    categoria = request.form.get("categoria", "").strip()
    descricao = request.form.get("descricao", "").strip()
    forma = request.form.get("forma_pagamento", "nao_informado").strip()
    status = request.form.get("status", "realizado").strip()
    chamado_id = request.form.get("chamado_id", "").strip()
    cliente_id = request.form.get("cliente_id", "").strip()
    funcionario_id = request.form.get("funcionario_id", "").strip()
    fornecedor = request.form.get("fornecedor", "").strip()
    observacoes = request.form.get("observacoes", "").strip()

    categorias_validas = CATEGORIAS_ENTRADA if tipo == "entrada" else CATEGORIAS_SAIDA
    if tipo not in ("entrada", "saida") or categoria not in categorias_validas:
        flash("Selecione o tipo e a categoria da movimentação.", "danger")
        return redirect(url_for("financeiro.index"))

    if not descricao:
        flash("Informe uma descrição para o lançamento.", "danger")
        return redirect(url_for("financeiro.index"))

    if forma not in FORMAS_PAGAMENTO or status not in STATUS_MOVIMENTO:
        flash("Forma de pagamento ou situação inválida.", "danger")
        return redirect(url_for("financeiro.index"))

    try:
        valor = converter_valor(request.form.get("valor"))
        data_movimento = converter_data(request.form.get("data_movimento"))
        data_vencimento = converter_data(request.form.get("data_vencimento")) if request.form.get("data_vencimento") else None
    except (InvalidOperation, ValueError, TypeError):
        flash("Informe um valor positivo e uma data válida.", "danger")
        return redirect(url_for("financeiro.index"))

    db = get_database()
    chamado = buscar_por_id(db["chamados"], chamado_id, usuario) if chamado_id else None
    cliente = buscar_por_id(db["clientes"], cliente_id, usuario) if cliente_id else None
    funcionario = buscar_por_id(db["funcionarios"], funcionario_id, usuario) if funcionario_id else None

    if chamado_id and not chamado:
        flash("O chamado selecionado não pertence à sua conta ou não existe.", "danger")
        return redirect(url_for("financeiro.index"))
    if cliente_id and not cliente:
        flash("O cliente selecionado não pertence à sua conta ou não existe.", "danger")
        return redirect(url_for("financeiro.index"))
    if funcionario_id and not funcionario:
        flash("O funcionário selecionado não pertence à sua conta ou não existe.", "danger")
        return redirect(url_for("financeiro.index"))

    if chamado and cliente and str(chamado.get("cliente_id", "")) != str(cliente["_id"]):
        flash("O cliente selecionado não corresponde ao cliente vinculado à obra.", "warning")
        return redirect(url_for("financeiro.index"))

    if tipo == "entrada" and categoria == "pagamento_obra" and not chamado:
        flash("Para registrar pagamento de obra, selecione o chamado correspondente.", "warning")
        return redirect(url_for("financeiro.index"))

    if chamado and tipo == "entrada" and status == "realizado":
        if "saldo_inicial_financeiro" not in chamado:
            db["chamados"].update_one(
                {"_id": chamado["_id"], "usuario_id": usuario, "saldo_inicial_financeiro": {"$exists": False}},
                {"$set": {"saldo_inicial_financeiro": float(chamado.get("valor_recebido", 0) or 0)}}
            )
            chamado = db["chamados"].find_one({"_id": chamado["_id"], "usuario_id": usuario}) or chamado

        saldo_disponivel = round(
            float(chamado.get("valor_final", 0) or 0)
            - float(chamado.get("valor_recebido", 0) or 0),
            2
        )
        if valor > saldo_disponivel + 0.001:
            flash(f"O valor excede o saldo pendente da obra (R$ {max(saldo_disponivel, 0):.2f}).", "warning")
            return redirect(url_for("financeiro.index"))

    registro = preparar_movimentacao(
        db, usuario, tipo, categoria, descricao, valor, data_movimento,
        status=status,
        forma_pagamento=forma,
        chamado_id=chamado["_id"] if chamado else None,
        chamado_numero=chamado.get("numero") if chamado else "",
        chamado_titulo=chamado.get("titulo") if chamado else "",
        cliente_id=cliente["_id"] if cliente else (chamado.get("cliente_id") if chamado else None),
        cliente_nome=cliente.get("nome") if cliente else (chamado.get("cliente_nome", "") if chamado else ""),
        funcionario_id=funcionario["_id"] if funcionario else None,
        funcionario_nome=funcionario.get("nome", "") if funcionario else "",
        fornecedor=fornecedor,
        observacoes=observacoes,
        data_vencimento=data_vencimento,
        origem="manual"
    )

    try:
        resultado = db["movimentacoes_financeiras"].insert_one(registro)
        if chamado and tipo == "entrada" and status == "realizado":
            atualizar_totais_chamado(db, usuario, chamado["_id"])
        flash("Movimentação financeira registrada com sucesso.", "success")
    except Exception:
        current_app.logger.exception("Erro ao registrar movimentação financeira.")
        flash("Não foi possível registrar a movimentação.", "danger")

    return redirect(url_for("financeiro.index", competencia=registro["competencia"]))


@financeiro_bp.route("/financeiro/lancamentos/<movimento_id>/realizar", methods=["POST"])
def marcar_como_realizado(movimento_id):
    usuario = usuario_id()
    if not usuario:
        return redirect(url_for("inicio"))
    if not ObjectId.is_valid(movimento_id):
        flash("Movimentação não encontrada.", "danger")
        return redirect(url_for("financeiro.index"))

    db = get_database()
    movimento = db["movimentacoes_financeiras"].find_one({
        "_id": ObjectId(movimento_id),
        "usuario_id": usuario,
        "cancelada": {"$ne": True},
        "status": "pendente"
    })
    if not movimento:
        flash("Não foi encontrada uma movimentação pendente para atualizar.", "warning")
        return redirect(url_for("financeiro.index"))

    # Antes de transformar uma previsão em recebimento real, confira o saldo
    # atual da obra. Isso evita que vários lançamentos pendentes ultrapassem
    # o valor contratado quando forem confirmados separadamente.
    if movimento.get("tipo") == "entrada" and movimento.get("chamado_id"):
        chamado = db["chamados"].find_one({
            "_id": movimento["chamado_id"],
            "usuario_id": usuario
        })
        if not chamado:
            flash("A obra vinculada não foi encontrada. O lançamento continua pendente.", "danger")
            return redirect(url_for("financeiro.index", competencia=movimento.get("competencia", "")))

        saldo_atual = max(
            round(
                float(chamado.get("valor_final", 0) or 0)
                - float(chamado.get("valor_recebido", 0) or 0),
                2
            ),
            0
        )
        if float(movimento.get("valor", 0) or 0) > saldo_atual + 0.001:
            flash(
                f"O valor ultrapassa o saldo atual da obra (R$ {saldo_atual:.2f}). Ajuste o lançamento antes de confirmar.",
                "warning"
            )
            return redirect(url_for("financeiro.index", competencia=movimento.get("competencia", "")))

    momento_realizacao = agora()
    db["movimentacoes_financeiras"].update_one(
        {"_id": movimento["_id"], "usuario_id": usuario, "status": "pendente"},
        {"$set": {
            "status": "realizado",
            "data_prevista": movimento.get("data_movimento"),
            "data_movimento": momento_realizacao,
            "data_pagamento": momento_realizacao,
            "competencia": obter_competencia(
                momento_realizacao,
                obter_dia_fechamento(db, usuario)
            ),
            "realizado_em": momento_realizacao,
            "atualizado_em": momento_realizacao
        }}
    )
    if movimento.get("tipo") == "entrada" and movimento.get("chamado_id"):
        atualizar_totais_chamado(db, usuario, movimento["chamado_id"])

    flash("Movimentação marcada como realizada.", "success")
    return redirect(url_for("financeiro.index", competencia=movimento.get("competencia", "")))


@financeiro_bp.route("/financeiro/lancamentos/<movimento_id>/cancelar", methods=["POST"])
def cancelar_movimentacao(movimento_id):
    usuario = usuario_id()
    if not usuario:
        return redirect(url_for("inicio"))
    if not ObjectId.is_valid(movimento_id):
        flash("Movimentação não encontrada.", "danger")
        return redirect(url_for("financeiro.index"))

    db = get_database()
    movimento = db["movimentacoes_financeiras"].find_one({
        "_id": ObjectId(movimento_id),
        "usuario_id": usuario,
        "cancelada": {"$ne": True}
    })
    if not movimento:
        flash("Movimentação não encontrada ou já cancelada.", "warning")
        return redirect(url_for("financeiro.index"))

    if movimento.get("origem") == "estoque":
        flash("Esta despesa veio do histórico de compras do estoque. Corrija o registro de origem para preservar a conciliação.", "warning")
        return redirect(url_for("financeiro.index", competencia=movimento.get("competencia", "")))

    agora_utc = agora()
    db["movimentacoes_financeiras"].update_one(
        {"_id": movimento["_id"], "usuario_id": usuario, "cancelada": {"$ne": True}},
        {"$set": {
            "cancelada": True,
            "cancelada_em": agora_utc,
            "cancelada_por": session.get("usuario_nome", "Usuário"),
            "atualizado_em": agora_utc
        }}
    )
    if movimento.get("tipo") == "entrada" and movimento.get("status") == "realizado" and movimento.get("chamado_id"):
        atualizar_totais_chamado(db, usuario, movimento["chamado_id"])

    flash("Movimentação cancelada. O histórico foi preservado.", "success")
    return redirect(url_for("financeiro.index", competencia=movimento.get("competencia", "")))
