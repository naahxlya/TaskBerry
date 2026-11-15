from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar


FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")


def data_atual():
    """Retorna a data atual no fuso horário do empreendimento."""
    return datetime.now(FUSO_HORARIO).date()


def agora_local():
    """Retorna data e hora atuais no fuso horário brasileiro."""
    return datetime.now(FUSO_HORARIO)


def ultimo_dia_mes(ano, mes):
    return calendar.monthrange(ano, mes)[1]


def adicionar_meses(ano, mes, quantidade):
    indice = ano * 12 + (mes - 1) + quantidade
    return indice // 12, indice % 12 + 1


def calcular_periodo(dia_fechamento=1, referencia=None):
    """
    Calcula o período financeiro atual.

    Dia 1: mês civil completo.
    Dia 25: período de 26 do mês anterior até 25 do mês atual.
    """

    if referencia is None:
        referencia = data_atual()

    dia_fechamento = max(1, min(int(dia_fechamento), 31))

    ano = referencia.year
    mes = referencia.month

    dia_limite_atual = min(
        dia_fechamento,
        ultimo_dia_mes(ano, mes)
    )

    data_limite = date(
        ano,
        mes,
        dia_limite_atual
    )

    if referencia <= data_limite:

        ano_anterior, mes_anterior = adicionar_meses(
            ano,
            mes,
            -1
        )

        dia_anterior = min(
            dia_fechamento,
            ultimo_dia_mes(ano_anterior, mes_anterior)
        )

        data_inicio = date(
            ano_anterior,
            mes_anterior,
            dia_anterior
        ) + timedelta(days=1)

        data_fim = data_limite

    else:

        ano_seguinte, mes_seguinte = adicionar_meses(
            ano,
            mes,
            1
        )

        dia_seguinte = min(
            dia_fechamento,
            ultimo_dia_mes(ano_seguinte, mes_seguinte)
        )

        data_inicio = data_limite + timedelta(days=1)

        data_fim = date(
            ano_seguinte,
            mes_seguinte,
            dia_seguinte
        )

    return {
        "inicio": data_inicio,
        "fim": data_fim,
        "referencia": referencia
    }


def formatar_data(data):
    return data.strftime("%d/%m/%Y")