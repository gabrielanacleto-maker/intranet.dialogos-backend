-- Migration: Create POPs tables and seed modules
-- Para bancos existentes que já possuem a pasta "POPs Gerais"

CREATE TABLE IF NOT EXISTS pop_modules (
    id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL,
    name TEXT NOT NULL,
    icon TEXT NOT NULL,
    position_order INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pop_files (
    id TEXT PRIMARY KEY,
    module_id TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mime_type TEXT DEFAULT '',
    uploaded_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pop_modules_folder ON pop_modules(folder_id);
CREATE INDEX IF NOT EXISTS idx_pop_files_module ON pop_files(module_id);

-- Seed modules for POPs Gerais (only if the folder exists and modules are empty)
DO $$
DECLARE
    v_folder_id TEXT;
    v_count INTEGER;
BEGIN
    SELECT id INTO v_folder_id FROM folders WHERE name = 'POPs Gerais' LIMIT 1;
    IF v_folder_id IS NOT NULL THEN
        SELECT COUNT(*) INTO v_count FROM pop_modules WHERE folder_id = v_folder_id;
        IF v_count = 0 THEN
            INSERT INTO pop_modules (id, folder_id, name, icon, position_order, created_at) VALUES
                (gen_random_uuid()::text, v_folder_id, 'Módulo Recepção', '/Recepção.png', 0, NOW() AT TIME ZONE 'UTC'),
                (gen_random_uuid()::text, v_folder_id, 'Módulo Financeiro', '/Financeiro.png', 1, NOW() AT TIME ZONE 'UTC'),
                (gen_random_uuid()::text, v_folder_id, 'Módulo Serviços Gerais', '/Limpeza.png', 2, NOW() AT TIME ZONE 'UTC'),
                (gen_random_uuid()::text, v_folder_id, 'Módulo Marketing', '/Marketing.png', 3, NOW() AT TIME ZONE 'UTC'),
                (gen_random_uuid()::text, v_folder_id, 'Módulo Comercial', '/Comercial.png', 4, NOW() AT TIME ZONE 'UTC');
        END IF;
    END IF;
END $$;
