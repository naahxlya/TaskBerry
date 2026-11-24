from datetime import datetime, timezone, timedelta


def _data_dentro_ultimos_12_meses(data):
    return not isinstance(data, datetime) or data.date() >= (datetime.now(timezone.utc).date() - timedelta(days=365))


def obter_competencia(data_movimento, dia_fechamento=30):
    """
    Retorna a competência (AAAA-MM) considerando o dia de fechamento mensal.
    Ex.: fechamento dia 30: movimentos de 01 a 30 pertencem ao mês corrente;
    movimentos após o dia 30 pertencem à competência seguinte.
    """
    if not isinstance(data_movimento, datetime):
        data_movimento = datetime.now(timezone.utc)

    dia_fechamento = max(1, min(int(dia_fechamento or 30), 31))
    if data_movimento.day > dia_fechamento:
        ano = data_movimento.year
        mes = data_movimento.month + 1
        if mes > 12:
            ano += 1
            mes = 1
        return f"{ano:04d}-{mes:02d}"

    return f"{data_movimento.year:04d}-{data_movimento.month:02d}"


def obter_dia_fechamento(db, usuario_id):
    configuracao = db["configuracoes"].find_one(
        {"usuario_id": usuario_id},
        {"dia_fechamento": 1}
    ) or {}
    return int(configuracao.get("dia_fechamento", 30) or 30)


def preparar_movimentacao(
    db,
    usuario_id,
    tipo,
    categoria,
    descricao,
    valor,
    data_movimento,
    **extras
):
    dia_fechamento = obter_dia_fechamento(db, usuario_id)
    agora = datetime.now(timezone.utc)

    registro = {
        "usuario_id": usuario_id,
        "tipo": tipo,
        "categoria": categoria,
        "descricao": descricao,
        "valor": round(float(valor), 2),
        "data_movimento": data_movimento,
        "competencia": obter_competencia(data_movimento, dia_fechamento),
        "status": extras.pop("status", "realizado"),
        "forma_pagamento": extras.pop("forma_pagamento", "nao_informado"),
        "criado_em": agora,
        "atualizado_em": agora,
        "cancelada": False,
    }
    registro.update(extras)
    return registro


def registrar_despesa_compra_material(db, usuario_id, movimentacao_estoque):
    """
    Espelha compras do estoque no financeiro. A origem é identificada pelo
    ObjectId da movimentação de estoque para impedir duplicidade.
    """
    valor_total = movimentacao_estoque.get("valor_total")
    if not valor_total or float(valor_total) <= 0:
        return None

    origem_id = movimentacao_estoque.get("_id")
    if origem_id and db["movimentacoes_financeiras"].find_one({
        "usuario_id": usuario_id,
        "origem_movimentacao_estoque_id": origem_id
    }):
        return None

    data_movimento = movimentacao_estoque.get("data_compra")
    if not data_movimento and movimentacao_estoque.get("material_id"):
        material = db["materiais"].find_one({
            "_id": movimentacao_estoque.get("material_id"),
            "usuario_id": usuario_id
        }, {"data_compra": 1})
        if material:
            data_movimento = material.get("data_compra")
    data_movimento = data_movimento or movimentacao_estoque.get("data") or datetime.now(timezone.utc)
    if not _data_dentro_ultimos_12_meses(data_movimento):
        return None
    nome = movimentacao_estoque.get("material_nome", "Material")
    fornecedor = movimentacao_estoque.get("fornecedor", "")

    registro = preparar_movimentacao(
        db,
        usuario_id,
        "saida",
        "materiais",
        f"Compra de material: {nome}",
        valor_total,
        data_movimento,
        status="realizado",
        forma_pagamento="nao_informado",
        fornecedor=fornecedor,
        material_nome=nome,
        material_id=movimentacao_estoque.get("material_id"),
        quantidade=movimentacao_estoque.get("quantidade"),
        valor_unitario=movimentacao_estoque.get("valor_unitario"),
        origem="estoque",
        origem_movimentacao_estoque_id=origem_id,
        observacoes="Despesa gerada automaticamente pelo registro de compra no estoque."
    )
    resultado = db["movimentacoes_financeiras"].insert_one(registro)
    return resultado.inserted_id


def sincronizar_compras_estoque(db, usuario_id):
    """
    Importa compras antigas do histórico de estoque uma única vez.
    Não importa consumos, ajustes ou movimentações sem valor total.
    """
    cursor = db["movimentacoes_estoque"].find({
        "usuario_id": usuario_id,
        "tipo": {"$in": ["compra", "compra_reabastecimento"]},
        "valor_total": {"$gt": 0}
    }).sort("data", 1)

    importadas = 0
    for item in cursor:
        if db["movimentacoes_financeiras "].find_one({
            "usuario_id": usuario_id,
            "origem_movimentacao_estoque_id": item["_id"]
        }, {"_id": 1}):
            continue
        try:
            if registrar_despesa_compra_material(db, usuario_id, item):
                importadas += 1
        except Exception:
            # Uma compra com dado legado incompleto não deve impedir o Financeiro.
            continue
    return importadas


def atualizar_totais_chamado(db, usuario_id, chamado_id):
    """
    Recalcula o total recebido no chamado a partir do razão financeiro.
    Preserva valores recebidos legados como saldo inicial de migração.
    """
    from bson import ObjectId

    if not ObjectId.is_valid(str(chamado_id)):
        return

    filtro_chamado = {
        "_id": ObjectId(str(chamado_id)),
        "usuario_id": usuario_id
    }
    chamado = db["chamados"].find_one(filtro_chamado)
    if not chamado:
        return

    if "saldo_inicial_financeiro" not in chamado:
        db["chamados"].update_one(
            {**filtro_chamado, "saldo_inicial_financeiro": {"$exists": False}},
            {"$set": {
                "saldo_inicial_financeiro": float(chamado.get("valor_recebido", 0) or 0)
            }}
        )
        chamado = db["chamados"].find_one(filtro_chamado) or chamado

    pipeline = [
        {"$match": {
            "usuario_id": usuario_id,
            "chamado_id": ObjectId(str(chamado_id)),
            "tipo": "entrada",
            "status": "realizado",
            "cancelada": {"$ne": True}
        }},
        {"$group": {"_id": None, "total": {"$sum": "$valor"}}}
    ]
    resultado = list(db["movimentacoes_financeiras"].aggregate(pipeline))
    total_lancado = float(resultado[0]["total"]) if resultado else 0.0
    saldo_inicial = float(chamado.get("saldo_inicial_financeiro", 0) or 0)
    recebido = round(saldo_inicial + total_lancado, 2)
    valor_final = float(chamado.get("valor_final", 0) or 0)
    saldo_pendente = 0.0 if chamado.get("status") == "cancelado" else round(max(valor_final - recebido, 0), 2)

    db["chamados"].update_one(
        filtro_chamado,
        {"$set": {
            "valor_recebido": recebido,
            "saldo_pendente": saldo_pendente,
            "atualizado_financeiro_em": datetime.now(timezone.utc)
        }}
    )


def registrar_despesa_aquisicao_ferramenta(db, usuario_id, ferramenta):
    aquisicao = ferramenta.get("aquisicao") or {}
    valor = (ferramenta.get("aquisicao") or {}).get(
        "valor", ferramenta.get("valor_aquisicao", 0)
    )
    if not valor or float(valor) <= 0:
        return None
    ferramenta_id = ferramenta.get("_id")
    if ferramenta_id and db["movimentacoes_financeiras"].find_one({
        "usuario_id": usuario_id,
        "origem_ferramenta_id": ferramenta_id
    }):
        return None

    data = aquisicao.get("data") or ferramenta.get("data_aquisicao") or datetime.now(timezone.utc)
    if not _data_dentro_ultimos_12_meses(data):
        return None
    fornecedor = aquisicao.get("fornecedor") or ferramenta.get("fornecedor", "")
    nome = ferramenta.get("nome", "Ferramenta")
    codigo = ferramenta.get("codigo", "")

    registro = preparar_movimentacao(
        db, usuario_id, "saida", "ferramentas",
        f"Aquisição de ferramenta: {nome}",
        valor, data,
        status="realizado",
        forma_pagamento="nao_informado",
        fornecedor=fornecedor,
        ferramenta_id=ferramenta_id,
        ferramenta_codigo=codigo,
        origem="ferramentas",
        origem_ferramenta_id=ferramenta_id,
        observacoes="Despesa gerada pelo cadastro de aquisição de ferramenta."
    )
    resultado = db["movimentacoes_financeiras"].insert_one(registro)
    db["ferramentas"].update_one(
        {"_id": ferramenta_id, "usuario_id": usuario_id},
        {"$set": {"aquisicao.integrado_erp": True}}
    )
    return resultado.inserted_id


def sincronizar_aquisicoes_ferramentas(db, usuario_id):
    cursor = db["ferramentas"].find({
        "usuario_id": usuario_id,
        "valor_aquisicao": {"$gt": 0}
    })
    importadas = 0
    for ferramenta in cursor:
        try:
            if registrar_despesa_aquisicao_ferramenta(db, usuario_id, ferramenta):
                importadas += 1
        except Exception:
            continue
    return importadas


def registrar_despesa_manutencao_ferramenta(
    db, usuario_id, ferramenta, manutencao, valor=None, data_movimento=None
):
    manutencao_id = manutencao.get("manutencao_id")
    if not manutencao_id:
        return None
    existente = db["movimentacoes_financeiras"].find_one({
        "usuario_id": usuario_id,
        "origem_manutencao_id": manutencao_id
    })
    valor_registro = valor
    if valor_registro is None:
        valor_registro = manutencao.get("valor_estimado", 0)
    if not valor_registro or float(valor_registro) <= 0:
        return None

    data = data_movimento or manutencao.get("data_envio") or datetime.now(timezone.utc)
    nome = ferramenta.get("nome", "Ferramenta")
    codigo = ferramenta.get("codigo", "")
    profissional = manutencao.get("profissional", "")

    if existente:
        db["movimentacoes_financeiras"].update_one(
            {"_id": existente["_id"], "usuario_id": usuario_id},
            {"$set": {
                "valor": round(float(valor_registro), 2),
                "data_movimento": data,
                "competencia": obter_competencia(data, obter_dia_fechamento(db, usuario_id)),
                "descricao": f"Manutenção de ferramenta: {nome}",
                "fornecedor": profissional,
                "status": existente.get("status", "pendente"),
                "atualizado_em": datetime.now(timezone.utc),
                "observacoes": manutencao.get("descricao", "")
            }}
        )
        return existente["_id"]

    registro = preparar_movimentacao(
        db, usuario_id, "saida", "ferramentas",
        f"Manutenção de ferramenta: {nome}",
        valor_registro, data,
        status="pendente",
        forma_pagamento="nao_informado",
        fornecedor=profissional,
        ferramenta_id=ferramenta.get("_id"),
        ferramenta_codigo=codigo,
        manutencao_id=manutencao_id,
        origem="manutencao_ferramenta",
        origem_manutencao_id=manutencao_id,
        observacoes=manutencao.get("descricao", "")
    )
    resultado = db["movimentacoes_financeiras"].insert_one(registro)
    return resultado.inserted_id
