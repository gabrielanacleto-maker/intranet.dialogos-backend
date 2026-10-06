-- Migration: Atendimentos e Descontos Bradescos
-- Lista de especialidades liberadas com os guias, o desconto Bradesco
-- e o valor recebido pelo profissional.

CREATE TABLE IF NOT EXISTS atendimentos_bradesco (
    id TEXT PRIMARY KEY,
    especialidades_liberadas TEXT NOT NULL,
    guias TEXT DEFAULT '',
    desconto_bradesco NUMERIC(12, 2) NOT NULL DEFAULT 0,
    valor_profissional NUMERIC(12, 2) NOT NULL DEFAULT 0,
    position_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_atendimentos_bradesco_order
    ON atendimentos_bradesco (position_order);