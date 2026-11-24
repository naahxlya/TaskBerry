// TaskBerry | Migração dos campos BSON da coleção movimentacoes_financeiras
// Execute no mongosh conectado ao banco taskberry.
// Não sobrescreve valores existentes: só cria os campos quando estão ausentes.

db.movimentacoes_financeiras.updateMany(
  { detalhes: { $exists: false } },
  { $set: {
      detalhes: {
        documento_referencia: "",
        centro_custo: "",
        observacao_interna: "",
        origem_registro: "migracao_legado"
      }
  } }
);

db.movimentacoes_financeiras.updateMany(
  { anexos: { $exists: false } },
  { $set: { anexos: [] } }
);

// Verificação: deve apresentar object e array entre os tipos encontrados.
db.movimentacoes_financeiras.aggregate([
  { $project: { campos: { $objectToArray: "$$ROOT" } } },
  { $unwind: "$campos" },
  { $group: { _id: { $type: "$campos.v" }, quantidade: { $sum: 1 } } },
  { $sort: { quantidade: -1 } }
]);
