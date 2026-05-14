-- =============================================================================
-- Migration: Sistema de Notificacoes v2 — Clinica Dialogos
-- =============================================================================
-- Executar no banco Neon (ou qualquer PostgreSQL) antes de reiniciar o backend.
-- =============================================================================

-- 1. Novas colunas na tabela existente (para compatibilidade com o novo formato)
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS actor_initials TEXT DEFAULT '';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS actor_color   TEXT DEFAULT '#c0395a';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_text   TEXT DEFAULT '';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS target_text   TEXT DEFAULT '';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS target_type   TEXT DEFAULT NULL;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link_url      TEXT DEFAULT NULL;

-- 2. Nova tabela com o schema exato do requisito (UUID, tipos definidos, FK)
CREATE TABLE IF NOT EXISTS notifications_v2 (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    actor_id    UUID NOT NULL REFERENCES users(id),
    type        VARCHAR(20) NOT NULL CHECK (type IN ('avaliacao','feed','reacao','comentario','mencao')),
    action      TEXT NOT NULL,
    target      TEXT,
    target_type VARCHAR(10),
    link        TEXT,
    read        BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Indices de performance
CREATE INDEX IF NOT EXISTS idx_notifications_v2_user_id   ON notifications_v2(user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_v2_user_read ON notifications_v2(user_id, read);
CREATE INDEX IF NOT EXISTS idx_notifications_v2_created   ON notifications_v2(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_v2_type      ON notifications_v2(type);

-- 3. Preencher actor_initials e actor_color para registros existentes (exemplo)
-- Ajuste conforme necessario para mapear sender_name → iniciais
UPDATE notifications
SET actor_initials = LEFT(sender_name, 1) || COALESCE(
    SUBSTRING(sender_name FROM ' (\w)'),
    ''
)
WHERE actor_initials = '' AND sender_name IS NOT NULL AND sender_name != '';
