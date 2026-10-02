-- =============================================================================
-- Migration: Notificacoes "v2" — Clinica Dialogos
-- =============================================================================
-- ESTE SCRIPT ESTA OBSOLETO. O schema v2 JA ESTA APLICADO e pode ser re-executado
-- com seguranca (todos os comandos sao idempotentes). Ele so documenta o que foi
-- feito e verifica o estado atual.
--
-- O QUE FOI REMOVIDO E POR QUE
--
-- 1) Tabela `notifications_v2`  (removida)
--    O script original criava uma tabela nova e falhava nela, porque declarava
--    REFERENCES users(id) — mas a tabela `users` nao tem coluna `id`
--    (a PK e `key`, do tipo TEXT). Erro: SQLSTATE 42703.
--
--    Depois de investigar, criar essa tabela nao resolveria nada: o "v2" e um
--    FORMATO DE RESPOSTA, nao uma tabela. Nenhum codigo le notifications_v2.
--      - Backend: GET /api/notifications/v2  ->  FROM notifications n
--                                                 LEFT JOIN users u ON n.sender_key = u.key
--      - Frontend: notificationService.js:90  ->  GET /api/notifications/v2
--    Criar a tabela deixaria um orfao sem efeito no sistema.
--
-- 2) Backfill de `actor_initials` / `actor_color`  (removido)
--    E desnecessario: o endpoint obtem iniciais e cor do JOIN com `users`
--    (u.initials / u.color) e, quando nao ha usuario correspondente, cai nos
--    fallbacks em Python _get_initials() / _get_actor_color()
--    (main.py, em get_notifications_v2).
--
-- O QUE CONTINUA VALENDO
--    As 6 colunas extras em `notifications`. Elas NAO sao criadas por
--    _ensure_notifications_table() (que so cria a tabela base e 4 indices),
--    entao o ADD COLUMN abaixo segue necessario para um banco novo.
--    Ressalva: hoje o endpoint v2 nao le actor_initials/actor_color (o alias
--    do JOIN tem precedencia) nem action_text/target_text/link_url
--    (ele usa title, message e reference_id). As colunas sao inertes.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1) Colunas extras em `notifications` (idempotente)
--    A tabela base + indices ja sao criados sozinhos por
--    _ensure_notifications_table() a cada start do backend.
-- -----------------------------------------------------------------------------
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS actor_initials TEXT DEFAULT '';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS actor_color   TEXT DEFAULT '#c0395a';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_text   TEXT DEFAULT '';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS target_text   TEXT DEFAULT '';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS target_type   TEXT DEFAULT NULL;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link_url      TEXT DEFAULT NULL;

-- Indices ja criados por _ensure_notifications_table(); repetidos aqui para
-- deixar o script auto-suficiente caso seja rodado num banco recem-criado.
CREATE INDEX IF NOT EXISTS idx_notif_target   ON notifications(target_user_key);
CREATE INDEX IF NOT EXISTS idx_notif_audience ON notifications(audience);
CREATE INDEX IF NOT EXISTS idx_notif_created  ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_read     ON notifications(is_read);


-- -----------------------------------------------------------------------------
-- 2) Verificacao
--    Le a tabela que o sistema realmente usa.
-- -----------------------------------------------------------------------------
SELECT COUNT(*) AS total_notificacoes FROM notifications;

-- types que o backend emite (main.py, argumento ntype de _notify):
--   system, vaga, celebration, mention, post, xp, feedback, comment,
--   comunicado, chat, ratimbum_reaction, humor
SELECT type, COUNT(*) AS qtd
FROM notifications
GROUP BY type
ORDER BY qtd DESC;

-- Confirma que notifications_v2 NAO e usada pelo sistema.
SELECT to_regclass('public.notifications_v2') AS notifications_v2_inexistente_esperado_NULL;
