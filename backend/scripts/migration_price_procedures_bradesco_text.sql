-- Migration: "Guias Bradesco" da tabela de preços aceita texto livre
-- Antes o campo era numérico; agora aceita número, texto ou caracteres
-- especiais (*&(%$#@...), pois o código do procedimento pode vir como
-- "50%", "consulta *", "R$ 80,00 &roidism" etc.

ALTER TABLE price_procedures
    ALTER COLUMN value_bradesco TYPE TEXT USING value_bradesco::TEXT;