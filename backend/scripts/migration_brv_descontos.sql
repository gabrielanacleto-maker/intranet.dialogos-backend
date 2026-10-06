-- Migration: Tabela de Descontos BRV
-- Lista plana de procedimentos com o desconto BRV, o desconto Bradesco
-- e o valor recebido pelo profissional.

CREATE TABLE IF NOT EXISTS brv_descontos (
    id TEXT PRIMARY KEY,
    procedimento TEXT NOT NULL,
    desconto_brv NUMERIC(12, 2) NOT NULL DEFAULT 0,
    desconto_brv_pct BOOLEAN NOT NULL DEFAULT FALSE,
    desconto_bradesco NUMERIC(12, 2) NOT NULL DEFAULT 0,
    desconto_bradesco_pct BOOLEAN NOT NULL DEFAULT FALSE,
    valor_profissional NUMERIC(12, 2) NOT NULL DEFAULT 0,
    position_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_brv_descontos_order ON brv_descontos (position_order);

-- Migração: unidades (_pct) em tabelas criadas antes das colunas existirem
ALTER TABLE brv_descontos ADD COLUMN IF NOT EXISTS desconto_brv_pct BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE brv_descontos ADD COLUMN IF NOT EXISTS desconto_bradesco_pct BOOLEAN NOT NULL DEFAULT FALSE;
