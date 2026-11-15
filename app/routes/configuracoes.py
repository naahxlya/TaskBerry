import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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


configuracoes_bp = Blueprint("configuracoes", __name__)

FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")
DIA_FECHAMENTO_PADRAO = 30


def obter_usuario_id():
    return session.get("usuario_id")


def obter_data_atual():
    return datetime.now(FUSO_HORARIO).date()


def obter_data_fechamento(ano, mes, dia):
    """Ajusta o dia de fechamento ao último dia do mês, quando necessário."""
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(dia, ultimo_dia))


def avancar_mes(ano, mes, quantidade=1):
    """Avança ou retrocede meses sem depender de bibliotecas externas."""
    indice = ano * 12 + (mes - 1) + quantidade
    novo_ano = indice // 12
    novo_mes = indice % 12 + 1

    return novo_ano, novo_mes


def calcular_periodo_atual(dia_fechamento, hoje=None):
    """
    Calcula o período financeiro conforme o dia de fechamento escolhido.

    Exemplo:
    Fechamento no dia 25:
    Período de 26 do mês anterior até 25 do mês atual.
    """
    hoje = hoje or obter_data_atual()

    fechamento_atual = obter_data_fechamento(
        hoje.year,
        hoje.month,
        dia_fechamento
    )

    if hoje <= fechamento_atual:
        ano_anterior, mes_anterior = avancar_mes(
            hoje.year,
            hoje.month,
            -1
        )

        fechamento_anterior = obter_data_fechamento(
            ano_anterior,
            mes_anterior,
            dia_fechamento
        )

        data_inicio = fechamento_anterior + timedelta(days=1)
        data_fim = fechamento_atual

    else:
        ano_proximo, mes_proximo = avancar_mes(
            hoje.year,
            hoje.month,
            1
        )

        data_inicio = fechamento_atual + timedelta(days=1)
        data_fim = obter_data_fechamento(
            ano_proximo,
            mes_proximo,
            dia_fechamento
        )

    return data_inicio, data_fim


def formatar_data(data):
    return data.strftime("%d/%m/%Y")


@configuracoes_bp.route("/configuracoes", methods=["GET", "POST"])
def minhas_configuracoes():
    usuario_id = obter_usuario_id()

    if not usuario_id:
        return redirect(url_for("inicio"))

    db = get_database()
    colecao = db["configuracoes"]

    configuracao = colecao.find_one({
        "usuario_id": usuario_id
    })

    if not configuracao:
        configuracao = {
            "usuario_id": usuario_id,
            "dia_fechamento": DIA_FECHAMENTO_PADRAO,
            "fuso_horario": "America/Sao_Paulo"
        }

    if request.method == "POST":
        try:
            dia_fechamento = int(
                request.form.get("dia_fechamento", "")
            )

            if dia_fechamento < 1 or dia_fechamento > 31:
                raise ValueError

        except (ValueError, TypeError):
            flash(
                "Selecione um dia de fechamento entre 1 e 31.",
                "danger"
            )

            return redirect(
                url_for("configuracoes.minhas_configuracoes")
            )

        dados_atualizados = {
            "dia_fechamento": dia_fechamento,
            "fuso_horario": "America/Sao_Paulo",
            "atualizado_em": datetime.now(FUSO_HORARIO)
        }

        try:
            colecao.update_one(
                {"usuario_id": usuario_id},
                {
                    "$set": dados_atualizados,
                    "$setOnInsert": {
                        "usuario_id": usuario_id,
                        "criado_em": datetime.now(FUSO_HORARIO)
                    }
                },
                upsert=True
            )

            flash(
                "Configurações salvas com sucesso!",
                "success"
            )

        except Exception:
            current_app.logger.exception(
                "Erro ao salvar as configurações do usuário."
            )

            flash(
                "Não foi possível salvar suas configurações.",
                "danger"
            )

        return redirect(
            url_for("configuracoes.minhas_configuracoes")
        )

    hoje = obter_data_atual()

    dia_fechamento = configuracao.get(
        "dia_fechamento",
        DIA_FECHAMENTO_PADRAO
    )

    data_inicio, data_fim = calcular_periodo_atual(
        dia_fechamento,
        hoje
    )

    return render_template(
        "configuracoes.html",
        configuracao=configuracao,
        dia_fechamento=dia_fechamento,
        data_atual=formatar_data(hoje),
        data_inicio=formatar_data(data_inicio),
        data_fim=formatar_data(data_fim),
        proximo_fechamento=formatar_data(data_fim)
    )