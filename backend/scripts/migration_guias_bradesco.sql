-- Migration: Adiciona pasta "Guias Bradesco"
INSERT INTO folders (id, name, icon, level, drive_link)
SELECT gen_random_uuid()::text, 'Guias Bradesco', '/bradesco.png', 'all', ''
WHERE NOT EXISTS (SELECT 1 FROM folders WHERE name = 'Guias Bradesco');

-- Migration: Atualiza ícone do "Recursos Humanos"
UPDATE folders SET icon = '/Recursos Humanos.png' WHERE name = 'Recursos Humanos' AND icon != '/Recursos Humanos.png';
