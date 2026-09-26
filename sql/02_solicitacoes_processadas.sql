CREATE TABLE IF NOT EXISTS solicitacoes_processadas (
    id_solicitacao TEXT PRIMARY KEY,
    processado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
