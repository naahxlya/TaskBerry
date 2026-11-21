from datetime import datetime, timezone, timedelta
import json

from bson import ObjectId
from flask import Blueprint, render_template, session, request, redirect, url_for
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

from app.database.connection import get_database


dashboard_bp = Blueprint("dashboard", __name__)


def _inicio_mes(data):
    return data.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _meses_retroativos(data, quantidade):
    atual = _inicio_mes(data)
    meses = []
    for deslocamento in range(quantidade - 1, -1, -1):
        ano = atual.year
        mes = atual.month - deslocamento
        while mes <= 0:
            mes += 12
            ano -= 1
        meses.append((ano, mes))
    return meses


def _data_segura(valor):
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor
    return None


def _dinheiro(valor):
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _formatar_moeda(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _criar_grafico_financeiro(meses, entradas, saidas):
    meses_pt = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]
    labels = [meses_pt[mes - 1] for _, mes in meses]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Entradas", x=labels, y=entradas,
        marker_color="#9B78D0", marker_line_width=0,
        hovertemplate="Entradas: R$ %{y:,.2f}<extra></extra>"
    ))
    fig.add_trace(go.Bar(
        name="Saídas", x=labels, y=saidas,
        marker_color="#E6A2C5", marker_line_width=0,
        hovertemplate="Saídas: R$ %{y:,.2f}<extra></extra>"
    ))
    fig.update_layout(
        barmode="group", height=310, margin=dict(l=12, r=12, t=16, b=12),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Nunito Sans, sans-serif", color="#82758F", size=11),
        legend=dict(orientation="h", y=1.16, x=0, font=dict(size=11)),
        xaxis=dict(showgrid=False, zeroline=False, fixedrange=True),
        yaxis=dict(showgrid=True, gridcolor="rgba(150,130,170,.13)", zeroline=False,
                   tickprefix="R$ ", tickformat="~s", fixedrange=True),
        hovermode="x unified"
    )
    return fig


def _criar_grafico_status(rotulos, valores):
    cores = ["#9B78D0", "#78B8A5", "#E7B96F", "#E6A2C5", "#B8A9C9"]
    fig = go.Figure(go.Pie(
        labels=rotulos, values=valores, hole=.68, sort=False,
        marker=dict(colors=cores, line=dict(color="rgba(255,255,255,.75)", width=2)),
        textinfo="percent", textposition="inside",
        hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"
    ))
    fig.update_layout(
        height=270, margin=dict(l=8, r=8, t=12, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Nunito Sans, sans-serif", color="#82758F", size=11),
        showlegend=True,
        legend=dict(orientation="h", y=-.12, x=.5, xanchor="center", font=dict(size=10))
    )
    return fig


def _grafico_json(fig):
    return json.dumps(fig, cls=PlotlyJSONEncoder)


@dashboard_bp.route("/dashboard")
def dashboard():
    usuario_id = session.get("usuario_id")
    if not usuario_id:
        return redirect(url_for("inicio"))

    db = get_database()
    usuario = None
    if ObjectId.is_valid(str(usuario_id)):
        usuario = db["usuarios"].find_one({"_id": ObjectId(str(usuario_id))})

    empresa_nome = (usuario.get("negocio", "").strip() if usuario else "") or "Meu empreendimento"
    nome_usuario = session.get("usuario_nome") or (usuario or {}).get("nome") or "Administrador"

    periodo = request.args.get("periodo", "6")
    if periodo not in ("3", "6", "12"):
        periodo = "6"
    quantidade_meses = int(periodo)

    agora = datetime.now(timezone.utc)
    meses = _meses_retroativos(agora, quantidade_meses)
    primeiro_mes = datetime(meses[0][0], meses[0][1], 1, tzinfo=timezone.utc)
    inicio_proximo_mes = (agora.replace(day=1) + timedelta(days=32)).replace(day=1)
    fim_periodo = inicio_proximo_mes

    filtro_ativo = {
        "usuario_id": usuario_id,
        "arquivado": {"$ne": True},
        "excluido": {"$ne": True}
    }
    filtro_usuario = {"usuario_id": usuario_id}

    clientes = db["clientes"]
    chamados = db["chamados"]
    movimentos = db["movimentacoes_financeiras"]
    materiais = db["materiais"]
    ferramentas = db["ferramentas"]
    funcionarios = db["funcionarios"]

    total_clientes = clientes.count_documents(filtro_ativo)
    total_chamados = chamados.count_documents(filtro_ativo)
    chamados_abertos = chamados.count_documents({
        **filtro_ativo, "status": {"$in": ["a_iniciar", "em_andamento", "aguardando"]}
    })
    chamados_concluidos = chamados.count_documents({**filtro_ativo, "status": "concluido"})
    chamados_atrasados = chamados.count_documents({
        **filtro_ativo, "status": {"$nin": ["concluido", "cancelado"]},
        "previsao_termino": {"$lt": agora}
    })

    filtro_movimento_periodo = {
        **filtro_usuario,
        "data_movimento": {"$gte": primeiro_mes, "$lt": fim_periodo},
        "cancelada": {"$ne": True},
        "status": "realizado"
    }
    movimentos_periodo = list(movimentos.find(filtro_movimento_periodo, {
        "tipo": 1, "valor": 1, "data_movimento": 1, "descricao": 1, "categoria": 1
    }))

    totais_mensais = {(ano, mes): {"entrada": 0.0, "saida": 0.0} for ano, mes in meses}
    total_entradas = total_saidas = 0.0
    for item in movimentos_periodo:
        data_mov = _data_segura(item.get("data_movimento"))
        if not data_mov:
            continue
        chave = (data_mov.year, data_mov.month)
        if chave not in totais_mensais:
            continue
        tipo = item.get("tipo")
        valor = _dinheiro(item.get("valor"))
        if tipo == "entrada":
            totais_mensais[chave]["entrada"] += valor
            total_entradas += valor
        elif tipo == "saida":
            totais_mensais[chave]["saida"] += valor
            total_saidas += valor

    saldo_periodo = total_entradas - total_saidas
    entradas_pendentes = sum(
        _dinheiro(x.get("valor")) for x in movimentos.find({
            **filtro_usuario, "tipo": "entrada", "status": "pendente",
            "cancelada": {"$ne": True}, "data_movimento": {"$gte": primeiro_mes, "$lt": fim_periodo}
        }, {"valor": 1})
    )
    saidas_pendentes = sum(
        _dinheiro(x.get("valor")) for x in movimentos.find({
            **filtro_usuario, "tipo": "saida", "status": "pendente",
            "cancelada": {"$ne": True}, "data_movimento": {"$gte": primeiro_mes, "$lt": fim_periodo}
        }, {"valor": 1})
    )

    rotulos_status = {
        "a_iniciar": "A iniciar", "em_andamento": "Em andamento",
        "aguardando": "Aguardando", "concluido": "Concluído", "cancelado": "Cancelado"
    }
    contagem_status = {key: 0 for key in rotulos_status}
    for item in chamados.find(filtro_ativo, {"status": 1}):
        status = item.get("status", "a_iniciar")
        if status in contagem_status:
            contagem_status[status] += 1

    grafico_financeiro = _criar_grafico_financeiro(
        meses,
        [round(totais_mensais[m]["entrada"], 2) for m in meses],
        [round(totais_mensais[m]["saida"], 2) for m in meses]
    )
    grafico_chamados = _criar_grafico_status(
        [rotulos_status[k] for k, v in contagem_status.items() if v],
        [v for v in contagem_status.values() if v]
    )

    chamados_recentes = list(chamados.find(filtro_ativo).sort(
        [("atualizado_em", -1), ("criado_em", -1)]
    ).limit(5))

    for chamado in chamados_recentes:
        chamado["status_label"] = rotulos_status.get(chamado.get("status"), "Não informado")
        chamado["data_dashboard"] = _data_segura(chamado.get("atualizado_em") or chamado.get("criado_em"))

    estoque_baixo = []
    for material in materiais.find(filtro_ativo, {
        "nome": 1, "quantidade_fechada": 1, "percentual_aberto": 1, "estoque_minimo": 1,
        "unidade_medida": 1
    }):
        saldo = _dinheiro(material.get("quantidade_fechada")) + (_dinheiro(material.get("percentual_aberto")) / 100)
        minimo = _dinheiro(material.get("estoque_minimo"))
        if saldo <= minimo:
            material["saldo_dashboard"] = round(saldo, 2)
            material["minimo_dashboard"] = minimo
            estoque_baixo.append(material)
    estoque_baixo.sort(key=lambda x: (x["saldo_dashboard"] - x["minimo_dashboard"], x.get("nome", "").lower()))
    estoque_baixo = estoque_baixo[:5]

    filtro_ferramentas = {"usuario_id": usuario_id, "arquivada": {"$ne": True}}
    total_ferramentas = ferramentas.count_documents(filtro_ferramentas)
    ferramentas_manutencao = ferramentas.count_documents({**filtro_ferramentas, "situacao": "manutencao"})
    ferramentas_em_uso = ferramentas.count_documents({**filtro_ferramentas, "situacao": "em_uso"})
    funcionarios_ativos = funcionarios.count_documents({
        **filtro_usuario, "excluido": {"$ne": True}, "situacao": {"$ne": "desligado"}
    })

    atividades = []
    for item in chamados.find(filtro_ativo, {"titulo": 1, "numero": 1, "historico": 1, "cliente_nome": 1}).sort("atualizado_em", -1).limit(12):
        for evento in item.get("historico", [])[-4:]:
            data_evento = _data_segura(evento.get("data"))
            if data_evento:
                atividades.append({
                    "data": data_evento, "titulo": evento.get("descricao") or "Chamado atualizado",
                    "detalhe": f'Chamado {item.get("numero", "")} · {item.get("titulo", "")}',
                    "icone": "bi-clipboard-check", "tipo": "chamado"
                })
    for item in movimentos.find(filtro_usuario, {
        "descricao": 1, "tipo": 1, "valor": 1, "data_movimento": 1, "cancelada": 1
    }).sort("data_movimento", -1).limit(8):
        data_evento = _data_segura(item.get("data_movimento"))
        if data_evento and not item.get("cancelada"):
            atividades.append({
                "data": data_evento, "titulo": item.get("descricao") or "Movimentação financeira",
                "detalhe": f'{ "Entrada" if item.get("tipo") == "entrada" else "Saída" } · {_formatar_moeda(_dinheiro(item.get("valor")))}',
                "icone": "bi-cash-coin", "tipo": "financeiro"
            })
    for item in db["movimentacoes_estoque"].find(filtro_usuario, {
        "material_nome": 1, "descricao": 1, "data": 1, "tipo": 1
    }).sort("data", -1).limit(6):
        data_evento = _data_segura(item.get("data"))
        if data_evento:
            atividades.append({
                "data": data_evento, "titulo": item.get("descricao") or "Movimentação de estoque",
                "detalhe": item.get("material_nome", "Material"), "icone": "bi-box-seam", "tipo": "estoque"
            })
    atividades.sort(key=lambda x: x["data"], reverse=True)
    atividades = atividades[:7]

    return render_template(
        "dashboard.html",
        empresa_nome=empresa_nome, nome_usuario=nome_usuario, periodo=periodo,
        total_clientes=total_clientes, total_chamados=total_chamados,
        chamados_abertos=chamados_abertos, chamados_concluidos=chamados_concluidos,
        chamados_atrasados=chamados_atrasados, total_entradas=total_entradas,
        total_saidas=total_saidas, saldo_periodo=saldo_periodo,
        entradas_pendentes=entradas_pendentes, saidas_pendentes=saidas_pendentes,
        total_ferramentas=total_ferramentas, ferramentas_manutencao=ferramentas_manutencao,
        ferramentas_em_uso=ferramentas_em_uso, funcionarios_ativos=funcionarios_ativos,
        estoque_baixo=estoque_baixo, chamados_recentes=chamados_recentes,
        atividades=atividades, grafico_financeiro=_grafico_json(grafico_financeiro),
        grafico_chamados=_grafico_json(grafico_chamados),
        periodo_label=f"últimos {quantidade_meses} meses", now_year=agora.year
    )
