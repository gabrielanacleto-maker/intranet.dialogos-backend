import psycopg2
import psycopg2.extras
import os
import uuid
import datetime

from auth import hash_password
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD")
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD")

if not DB_URL:
    raise ValueError("DATABASE_URL não configurada")
print(f"DB_URL carregada: {DB_URL[:30]}...")

if not ADMIN_DEFAULT_PASSWORD or not DEFAULT_USER_PASSWORD:
    raise ValueError("Senhas padrão não configuradas")

class SmartCursor:
    def __init__(self, cursor, conn):
        self._cursor = cursor
        self._conn = conn

    def execute(self, *args, **kwargs):
        self._cursor.execute(*args, **kwargs)
        return self._cursor

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._cursor, name)

@contextmanager
def get_db_context():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cursor = SmartCursor(conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor), conn)
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor._cursor.close()
        conn.close()

def get_db():
    with get_db_context() as cursor:
        yield cursor

def _column_exists(cursor, table, column):
    cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s",
        (table, column)
    )
    return cursor.fetchone() is not None

def _table_exists(cursor, table):
    cursor.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name=%s",
        (table,)
    )
    return cursor.fetchone() is not None

def _safe_add_column(cursor, table, column, col_def):
    if _table_exists(cursor, table) and not _column_exists(cursor, table, column):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")

def _safe_drop_constraint(cursor, table, constraint):
    if _table_exists(cursor, table):
        cursor.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")

def _safe_update_existing(cursor, table, set_expr, where_expr):
    if _table_exists(cursor, table):
        cursor.execute(f"UPDATE {table} SET {set_expr} WHERE {where_expr}")

# ── ESTRUTURA DE CARGOS MULTIEMPRESA ────────────────────────────────────────
# Templates de inicialização por empresa (editáveis/removíveis pelo cliente;
# nunca regras fixas do sistema).

TRILHAS_PADRAO = ["Operacional", "Administrativa/Business", "Técnica", "Profissional", "Gestão"]
SENIORIDADES_PADRAO = ["Não aplicável", "Júnior", "Pleno", "Sênior", "Especialista", "Lead/Líder Técnico"]
NIVEIS_HIERARQUICOS_PADRAO = ["Operacional", "Profissional", "Supervisão", "Coordenação", "Gerência", "Diretoria", "Executivo"]

_ESTRUTURA_TABLES = ("departamentos", "familias_cargo", "trilhas", "senioridades", "niveis_hierarquicos")

def _criar_tabelas_estrutura(cursor):
    for table in _ESTRUTURA_TABLES:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                empresa_id TEXT NOT NULL,
                nome TEXT NOT NULL,
                descricao TEXT DEFAULT '',
                ordem INTEGER DEFAULT 0,
                ativo INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_empresa ON {table}(empresa_id)")

def _seed_catalogo(cursor, table, empresa_id, nomes):
    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE empresa_id=%s", (empresa_id,))
    if cursor.fetchone()[0] > 0:
        return
    now = datetime.datetime.utcnow().isoformat()
    cursor.executemany(
        f"INSERT INTO {table} (id, empresa_id, nome, ordem, ativo, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        [(str(uuid.uuid4()), empresa_id, nome, i, 1, now) for i, nome in enumerate(nomes)],
    )

def seed_estrutura_padrao(cursor, empresa_id):
    """Popula trilhas/senioridades/níveis padrão de uma empresa (idempotente).
    Chamado no init_db para empresas existentes e ao criar novas empresas."""
    _seed_catalogo(cursor, "trilhas", empresa_id, TRILHAS_PADRAO)
    _seed_catalogo(cursor, "senioridades", empresa_id, SENIORIDADES_PADRAO)
    _seed_catalogo(cursor, "niveis_hierarquicos", empresa_id, NIVEIS_HIERARQUICOS_PADRAO)

def _seed_dart_v1(cursor):
    """Cria a versão v1 do teste (se não existir) e insere as 25 perguntas
    com as alternativas associadas aos perfis. A ordem das alternativas é
    embaralhada por pergunta (o perfil não fica sempre na mesma posição)."""
    import random
    from dart_data import DART_QUESTIONS_V1, DART_PERFIS

    cursor.execute("SELECT id FROM dart_teste_versoes WHERE nome=%s", ("DART v1.0",))
    row = cursor.fetchone()
    if row:
        return
    versao_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    cursor.execute(
        "INSERT INTO dart_teste_versoes (id, nome, total_questoes, ativo, created_at) VALUES (%s,%s,%s,%s,%s)",
        (versao_id, "DART v1.0", len(DART_QUESTIONS_V1), 1, now),
    )
    qids = []
    for i, q in enumerate(DART_QUESTIONS_V1):
        qid = str(uuid.uuid4())
        qids.append(qid)
        cursor.execute(
            "INSERT INTO dart_perguntas (id, versao_id, texto, status, ordem, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (qid, versao_id, q["texto"], "ativo", i + 1, now),
        )
        perfis_ord = list(DART_PERFIS)
        random.shuffle(perfis_ord)
        for j, perfil in enumerate(perfis_ord):
            cursor.execute(
                "INSERT INTO dart_alternativas (id, pergunta_id, texto, perfil, ordem, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                (str(uuid.uuid4()), qid, q["alternativas"][perfil], perfil, j + 1, now),
            )

def init_db():
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()

    try:
        _safe_add_column(c, 'users', 'about_me', "about_me TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'is_diretor', "is_diretor INTEGER DEFAULT 0")
        _safe_add_column(c, 'users', 'is_leader', "is_leader INTEGER DEFAULT 0")
        _safe_add_column(c, 'posts', 'video_url', "video_url TEXT DEFAULT ''")
        _safe_add_column(c, 'posts', 'author_role', "author_role TEXT DEFAULT ''")
        _safe_add_column(c, 'posts', 'author_is_rh', "author_is_rh INTEGER DEFAULT 0")
        _safe_add_column(c, 'posts', 'author_is_admin', "author_is_admin INTEGER DEFAULT 0")
        _safe_add_column(c, 'posts', 'reactions', "reactions TEXT DEFAULT '{}'")

        _safe_add_column(c, 'users', 'is_orcoma', "is_orcoma INTEGER DEFAULT 0")
        _safe_add_column(c, 'users', 'hire_date', "hire_date TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'org_position', "org_position TEXT DEFAULT 'colaborador'")
        _safe_add_column(c, 'users', 'manager_key', "manager_key TEXT DEFAULT NULL")
        _safe_add_column(c, 'users', 'nivel_dourado', "nivel_dourado INTEGER DEFAULT 0")
        _safe_add_column(c, 'users', 'desligado', "desligado INTEGER DEFAULT 0")
        _safe_add_column(c, 'users', 'desligado_data', "desligado_data TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'desligamento_motivo', "desligamento_motivo TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'desligamento_obs', "desligamento_obs TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'cargo_id', "cargo_id TEXT DEFAULT NULL")
        _safe_add_column(c, 'users', 'senioridade', "senioridade TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'senioridade_id', "senioridade_id TEXT DEFAULT NULL")
        _safe_add_column(c, 'users', 'departamento_id', "departamento_id TEXT DEFAULT NULL")
        _safe_add_column(c, 'users', 'empresa_id', "empresa_id TEXT DEFAULT NULL")
        _safe_add_column(c, 'users', 'email', "email TEXT DEFAULT ''")
        _safe_add_column(c, 'users', 'dart', "dart TEXT DEFAULT ''")

        c.execute("""
            CREATE TABLE IF NOT EXISTS cargos (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                nivel INTEGER DEFAULT 0,
                created_at TEXT DEFAULT ''
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS cargos_gerais (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                created_at TEXT DEFAULT ''
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS empresas (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                cnpj TEXT DEFAULT '',
                socios TEXT DEFAULT '',
                endereco TEXT DEFAULT '',
                logo TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
        """)

        c.execute("""INSERT INTO empresas (id, nome, cnpj, socios, endereco, logo, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            ('dialogos', 'Clínica Diálogos', '', '', '', '', '2026-01-01T00:00:00'))
        c.execute("""INSERT INTO empresas (id, nome, cnpj, socios, endereco, logo, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
            ('orcoma', 'Orcoma Contabilidade', '', '', '', '', '2026-01-01T00:00:00'))

        c.execute("""
            CREATE TABLE IF NOT EXISTS carreira_historico (
                id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                cargo TEXT NOT NULL,
                start_date TEXT DEFAULT '',
                end_date TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_carreira_historico_user ON carreira_historico(user_key)")
        _safe_add_column(c, 'carreira_historico', 'cargo_id', "cargo_id TEXT DEFAULT NULL")
        _safe_add_column(c, 'carreira_historico', 'senioridade_id', "senioridade_id TEXT DEFAULT NULL")

        c.execute("UPDATE users SET empresa_id='orcoma' WHERE is_orcoma=1 AND (empresa_id IS NULL OR empresa_id='')")
        c.execute("UPDATE users SET empresa_id='dialogos' WHERE is_orcoma=0 AND (empresa_id IS NULL OR empresa_id='')")

        # ── Estrutura de cargos multiempresa: tabelas, colunas e seeds ──
        _criar_tabelas_estrutura(c)

        for col in ("empresa_id", "departamento_id", "familia_id", "trilha_id",
                    "nivel_hierarquico_id"):
            _safe_add_column(c, 'cargos', col, f"{col} TEXT DEFAULT NULL")
        _safe_add_column(c, 'cargos', 'descricao', "descricao TEXT DEFAULT ''")
        _safe_add_column(c, 'cargos', 'ativo', "ativo INTEGER DEFAULT 1")
        c.execute("CREATE INDEX IF NOT EXISTS idx_cargos_empresa ON cargos(empresa_id)")

        # Cargos existentes tornam-se dados iniciais da empresa atual
        c.execute("UPDATE cargos SET empresa_id='dialogos' WHERE empresa_id IS NULL OR empresa_id=''")

        # Templates padrão para cada empresa já existente (idempotente)
        c.execute("SELECT id FROM empresas")
        for emp_row in c.fetchall():
            seed_estrutura_padrao(c, emp_row[0])

        # Mapeia senioridade textual legada (''/jr/pl/sr) para senioridade_id
        c.execute("""
            UPDATE users u SET senioridade_id = s.id
            FROM senioridades s
            WHERE s.empresa_id = COALESCE(NULLIF(u.empresa_id,''),'dialogos')
              AND u.senioridade_id IS NULL
              AND (
                   (COALESCE(u.senioridade,'')='' AND s.nome='Não aplicável')
                OR (u.senioridade='jr' AND s.nome='Júnior')
                OR (u.senioridade='pl' AND s.nome='Pleno')
                OR (u.senioridade='sr' AND s.nome='Sênior')
              )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS post_views (
                id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                post_id TEXT NOT NULL,
                viewed_at TEXT NOT NULL,
                UNIQUE(user_key, post_id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                employee_id TEXT NOT NULL,
                evaluator_id TEXT NOT NULL,
                evaluation_type TEXT NOT NULL CHECK(evaluation_type IN ('leader','rh','diretor')),
                positive_feedback TEXT DEFAULT '',
                negative_feedback TEXT DEFAULT '',
                extra_notes TEXT DEFAULT '',
                score_delta INTEGER DEFAULT 0,
                stars INTEGER DEFAULT 0 CHECK(stars >= 0 AND stars <= 5),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS presence (
                user_key TEXT PRIMARY KEY,
                is_online INTEGER DEFAULT 0,
                last_seen TEXT,
                last_activity TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS colleague_feedback (
                id TEXT PRIMARY KEY,
                target_user_key TEXT NOT NULL,
                author_key TEXT NOT NULL,
                text TEXT NOT NULL,
                rating INTEGER,
                is_private INTEGER DEFAULT 0,
                reactions TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

        # Migração: tabelas criadas antes das colunas rating/is_private existirem
        try:
            c.execute("ALTER TABLE colleague_feedback ADD COLUMN IF NOT EXISTS rating INTEGER")
            c.execute("ALTER TABLE colleague_feedback ADD COLUMN IF NOT EXISTS is_private INTEGER DEFAULT 0")
        except Exception:
            pass

        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target_user_id TEXT,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                color TEXT DEFAULT '#C9A84C',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                all_day INTEGER DEFAULT 0,
                is_public INTEGER DEFAULT 0,
                repeat_type TEXT DEFAULT 'none',
                created_by TEXT DEFAULT '',
                user_key TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        _safe_add_column(c, 'folders', 'nivel_dourado', "nivel_dourado INTEGER DEFAULT 0")
        _safe_add_column(c, 'folders', 'created_by', "created_by TEXT DEFAULT ''")
        _safe_add_column(c, 'calendar_events', 'user_key', "user_key TEXT DEFAULT ''")

        _safe_update_existing(c, 'calendar_events',
            "user_key = created_by",
            "user_key = '' OR user_key IS NULL"
        )

        c.execute("SELECT 1 FROM users WHERE key=%s", ('gabriel',))
        if not c.fetchone():
            c.execute("""INSERT INTO users
                (key, name, initials, role, dept, level, color, access_level,
                 is_admin, is_admin_user, is_rh, is_ouvidor, points, password_hash, password_changed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                ('gabriel', 'Gabriel Anacleto de Souza Cruz', 'GA',
                 'Auxiliar Financeiro Jr', 'Financeiro & System Adm',
                 'diamante', 'av-gold', 3, 1, 0, 0, 0, 100,
                 hash_password(ADMIN_DEFAULT_PASSWORD), 1)
            )

        c.execute("SELECT 1 FROM users WHERE key=%s", ('tairla',))
        if not c.fetchone():
            c.execute("""INSERT INTO users
                (key, name, initials, role, dept, level, color, access_level,
                 is_admin, is_admin_user, is_rh, is_ouvidor, is_diretor, is_leader, points, password_hash, password_changed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                ('tairla', 'Tairla Andrade Carvalho Mascarenhas', 'TA',
                 'Diretora', 'Administrativo & User Adm',
                 'diamante', 'av-teal', 2, 0, 1, 1, 0, 1, 0, 100,
                 hash_password(DEFAULT_USER_PASSWORD), 0)
            )

        c.execute("SELECT 1 FROM users WHERE key=%s", ('malu',))
        if not c.fetchone():
            c.execute("""INSERT INTO users
                (key, name, initials, role, dept, level, color, access_level,
                 is_admin, is_admin_user, is_rh, is_ouvidor, is_diretor, is_leader, points, password_hash, password_changed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                ('malu', 'Maria Luiza Alves Macedo', 'MA',
                 'Líder', 'Administrativo',
                 'platina', 'av-blue', 1, 0, 0, 0, 1, 0, 1, 100,
                 hash_password(DEFAULT_USER_PASSWORD), 0)
            )

        c.execute("SELECT COUNT(*) FROM folders")
        if c.fetchone()[0] == 0:
            default_folders = [
                (str(uuid.uuid4()), 'Guias Bradesco', '/bradesco.png', 'all', ''),
                (str(uuid.uuid4()), 'POPs Gerais', '/Pops.png', 'all', ''),
                (str(uuid.uuid4()), 'POPs Financeiros', '📊', 'platina', ''),
                (str(uuid.uuid4()), 'Contratos & Relatórios', '📑', 'diamante', ''),
                (str(uuid.uuid4()), 'Tabela de Preços', '💲', 'dourado', ''),
                (str(uuid.uuid4()), 'Organograma', '🏢', 'all', ''),
                (str(uuid.uuid4()), 'Recursos Humanos', '/Recursos Humanos.png', 'rh', ''),
                (str(uuid.uuid4()), 'Treinamentos', '🎓', 'all', ''),
                (str(uuid.uuid4()), 'Gestão de Acessos', '🔐', 'diamante', ''),
                (str(uuid.uuid4()), 'Especialidades', '/especialidades-medicas.png', 'all', ''),
            ]
            c.executemany(
                "INSERT INTO folders (id, name, icon, level, drive_link) VALUES (%s,%s,%s,%s,%s)",
                default_folders
            )

        c.execute("""
            CREATE TABLE IF NOT EXISTS pop_modules (
                id TEXT PRIMARY KEY,
                folder_id TEXT NOT NULL,
                name TEXT NOT NULL,
                icon TEXT NOT NULL,
                position_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pop_files (
                id TEXT PRIMARY KEY,
                module_id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                size INTEGER NOT NULL DEFAULT 0,
                mime_type TEXT DEFAULT '',
                uploaded_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pop_modules_folder ON pop_modules(folder_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pop_files_module ON pop_files(module_id)")

        c.execute("SELECT id FROM folders WHERE name='POPs Gerais'")
        row = c.fetchone()
        if row:
            pops_folder_id = row[0]
            c.execute("SELECT COUNT(*) FROM pop_modules WHERE folder_id=%s", (pops_folder_id,))
            if c.fetchone()[0] == 0:
                pop_modules = [
                    (str(uuid.uuid4()), pops_folder_id, 'Módulo Recepção', '/Recepção.png', 0),
                    (str(uuid.uuid4()), pops_folder_id, 'Módulo Financeiro', '/Financeiro.png', 1),
                    (str(uuid.uuid4()), pops_folder_id, 'Módulo Serviços Gerais', '/Limpeza.png', 2),
                    (str(uuid.uuid4()), pops_folder_id, 'Módulo Marketing', '/Marketing.png', 3),
                    (str(uuid.uuid4()), pops_folder_id, 'Módulo Comercial', '/Comercial.png', 4),
                ]
                c.executemany(
                    "INSERT INTO pop_modules (id, folder_id, name, icon, position_order, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    [(mid, fid, name, icon, pos, datetime.datetime.utcnow().isoformat()) for mid, fid, name, icon, pos in pop_modules]
                )

        c.execute("SELECT COUNT(*) FROM social_rooms")
        if c.fetchone()[0] == 0:
            room_id = str(uuid.uuid4())
            c.execute("""INSERT INTO social_rooms
                (id, name, description, created_by, created_at)
                VALUES (%s,%s,%s,%s,%s)""",
                (room_id, 'Sala Geral',
                 'Canal principal da clínica para alinhamentos rápidos.',
                 'gabriel', '2026-04-22T00:00:00')
            )
            c.execute("""INSERT INTO social_room_members
                (id, room_id, user_key, added_by, created_at)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING""",
                (str(uuid.uuid4()), room_id, 'gabriel',
                 'gabriel', '2026-04-22T00:00:00')
            )

        _safe_add_column(c, 'tarefas', 'status', "status TEXT DEFAULT 'pendente'")
        _safe_add_column(c, 'tarefas', 'custom_status', "custom_status TEXT DEFAULT NULL")
        _safe_add_column(c, 'tarefas', 'prioridade', "prioridade TEXT DEFAULT 'media'")
        _safe_add_column(c, 'tarefas', 'tipo_tarefa', "tipo_tarefa TEXT DEFAULT 'tarefa'")
        _safe_add_column(c, 'tarefas', 'recorrencia', "recorrencia TEXT DEFAULT 'nenhuma'")
        _safe_add_column(c, 'tarefas', 'duration_seconds', "duration_seconds INTEGER DEFAULT 0")
        _safe_add_column(c, 'tarefas', 'started_at', "started_at TEXT DEFAULT NULL")
        _safe_add_column(c, 'tarefas', 'ended_at', "ended_at TEXT DEFAULT NULL")
        _safe_add_column(c, 'tarefas', 'delay_reason', "delay_reason TEXT DEFAULT NULL")
        _safe_add_column(c, 'tarefas', 'delayed_at', "delayed_at TEXT DEFAULT NULL")
        _safe_add_column(c, 'tarefas', 'paused_seconds', "paused_seconds INTEGER DEFAULT 0")
        _safe_add_column(c, 'tarefas', 'delegated_by', "delegated_by TEXT DEFAULT NULL")
        _safe_add_column(c, 'tarefas', 'concluida_em', "concluida_em TEXT DEFAULT NULL")

        _safe_drop_constraint(c, 'tarefas', 'tarefas_tipo_check')

        c.execute("""
            CREATE TABLE IF NOT EXISTS ouvidoria (
                id TEXT PRIMARY KEY,
                author_key TEXT NOT NULL,
                author_name TEXT NOT NULL,
                category TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'aberta',
                anonymous INTEGER NOT NULL DEFAULT 0,
                responses TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            )
        """)

        _safe_add_column(c, 'ouvidoria', 'anonymous', "anonymous INTEGER DEFAULT 0")

        c.execute("""
            CREATE TABLE IF NOT EXISTS melhoria_sugestoes (
                id TEXT PRIMARY KEY,
                author_key TEXT NOT NULL,
                text TEXT NOT NULL,
                is_done INTEGER DEFAULT 0,
                done_reason TEXT DEFAULT '',
                status_by_key TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sugestoes_created ON melhoria_sugestoes(created_at DESC)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS task_comments (
                id TEXT PRIMARY KEY,
                tarefa_id TEXT NOT NULL,
                author_key TEXT NOT NULL,
                author_name TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tarefa_id) REFERENCES tarefas(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id TEXT PRIMARY KEY,
                tarefa_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_key TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (tarefa_id) REFERENCES tarefas(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS communications (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_key TEXT NOT NULL,
                author_name TEXT NOT NULL,
                is_draft INTEGER NOT NULL DEFAULT 1,
                is_published INTEGER NOT NULL DEFAULT 0,
                published_at TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                deleted_by_key TEXT,
                target_audience TEXT NOT NULL DEFAULT 'all',
                priority TEXT NOT NULL DEFAULT 'normal',
                views_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS communication_reads (
                id TEXT PRIMARY KEY,
                communication_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                read_at TEXT NOT NULL,
                read_count INTEGER NOT NULL DEFAULT 1,
                UNIQUE(communication_id, user_key)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS communication_notifications (
                id TEXT PRIMARY KEY,
                communication_id TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                total_recipients INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_author ON communications(author_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_published ON communications(is_published)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_deleted ON communications(is_deleted)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_audience ON communications(target_audience)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_created ON communications(created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_reads_comm ON communication_reads(communication_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_reads_user ON communication_reads(user_key)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratimbum_posts (
                id TEXT PRIMARY KEY,
                author_key TEXT NOT NULL,
                author_name TEXT NOT NULL,
                author_initials TEXT NOT NULL,
                author_color TEXT NOT NULL DEFAULT 'av-gold',
                author_photo_url TEXT DEFAULT '',
                author_role TEXT DEFAULT '',
                author_type TEXT NOT NULL DEFAULT 'user' CHECK(author_type IN ('user','system')),
                text TEXT NOT NULL,
                mentions TEXT DEFAULT '[]',
                reactions TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ratimbum_reactions (
                id TEXT PRIMARY KEY,
                post_id TEXT NOT NULL REFERENCES ratimbum_posts(id),
                user_key TEXT NOT NULL,
                emoji TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(post_id, user_key, emoji)
            )
        """)
        _safe_add_column(c, 'ratimbum_posts', 'parent_id', "parent_id TEXT DEFAULT NULL")
        _safe_add_column(c, 'ratimbum_posts', 'is_celebration', "is_celebration INTEGER DEFAULT 1")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ratimbum_posts_created ON ratimbum_posts(created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ratimbum_reactions_post ON ratimbum_reactions(post_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS post_reactions (
                id TEXT PRIMARY KEY,
                post_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                emoji TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(post_id, user_key, emoji)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_post_reactions_post ON post_reactions(post_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                event_date TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date DESC)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS evento (
                id TEXT PRIMARY KEY,
                titulo TEXT DEFAULT '',
                data_inicio TEXT NOT NULL,
                data_termino TEXT NOT NULL,
                apng_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_evento_datas ON evento(data_inicio, data_termino)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_posts_feed_created ON posts(feed, pinned, created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_post_views_post ON post_views(post_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ratimbum_posts_author ON ratimbum_posts(author_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_comm_reads_user_comm ON communication_reads(user_key, communication_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS pdis (
                id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                titulo TEXT NOT NULL,
                descricao TEXT DEFAULT '',
                data_inicio TEXT NOT NULL,
                data_fim TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ativo',
                data_conclusao TEXT DEFAULT '',
                justificativa_expiracao TEXT DEFAULT '',
                blocos TEXT DEFAULT '[]',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pdis_user ON pdis(user_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_pdis_status ON pdis(status)")

        _safe_add_column(c, 'pdis', 'template_id', "template_id TEXT DEFAULT NULL")

        c.execute("""
            CREATE TABLE IF NOT EXISTS pdi_templates (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT DEFAULT '',
                tipo TEXT NOT NULL DEFAULT 'desenvolvimento',
                auto_onboarding INTEGER DEFAULT 0,
                blocos TEXT DEFAULT '[]',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_pdi_templates_tipo ON pdi_templates(tipo)")

        # ── CONTRATAÇÃO ──
        c.execute("""
            CREATE TABLE IF NOT EXISTS vagas (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                senioridade TEXT DEFAULT '',
                descricao TEXT DEFAULT '',
                salario TEXT DEFAULT '',
                requisitos TEXT DEFAULT '',
                expectativas TEXT DEFAULT '',
                formacao TEXT DEFAULT '',
                palavras_chave TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'em_analise',
                motivo_rejeicao TEXT DEFAULT '',
                created_by TEXT NOT NULL,
                created_by_name TEXT DEFAULT '',
                apply_token TEXT DEFAULT '',
                deadline TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_vagas_status ON vagas(status)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS vaga_candidaturas (
                id TEXT PRIMARY KEY,
                vaga_id TEXT NOT NULL,
                nome TEXT NOT NULL,
                email TEXT DEFAULT '',
                telefone TEXT DEFAULT '',
                respostas TEXT DEFAULT '{}',
                disc TEXT DEFAULT '{}',
                curriculo_url TEXT DEFAULT '',
                curriculo_nome TEXT DEFAULT '',
                score REAL,
                score_breakdown TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'recebido',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_candidaturas_vaga ON vaga_candidaturas(vaga_id)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS experiencia_registros (
                user_key TEXT PRIMARY KEY,
                start_date TEXT DEFAULT '',
                end_date TEXT DEFAULT '',
                resultado TEXT DEFAULT '',
                notas TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_reset_token ON password_reset_tokens(token)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_reset_email ON password_reset_tokens(email)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS pesquisas (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                pergunta TEXT NOT NULL,
                escala_max INTEGER DEFAULT 10,
                criado_por TEXT NOT NULL,
                criado_por_nome TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                expires_at TEXT DEFAULT NULL
            )
        """)
        # Migração: tabelas criadas antes da coluna is_active existir
        try:
            c.execute("ALTER TABLE pesquisas ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1")
        except Exception:
            pass
        c.execute("CREATE INDEX IF NOT EXISTS idx_pesquisas_active ON pesquisas(is_active, created_at)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS pesquisa_respostas (
                id TEXT PRIMARY KEY,
                pesquisa_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                nota INTEGER NOT NULL,
                comentario TEXT DEFAULT '',
                anonima INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(pesquisa_id, user_key)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_respostas_pesquisa ON pesquisa_respostas(pesquisa_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_respostas_user ON pesquisa_respostas(user_key)")

        # ── DART — Avaliação de Perfil Comportamental ──
        c.execute("""
            CREATE TABLE IF NOT EXISTS dart_teste_versoes (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                total_questoes INTEGER DEFAULT 25,
                ativo INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS dart_perguntas (
                id TEXT PRIMARY KEY,
                versao_id TEXT NOT NULL,
                texto TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ativo',
                ordem INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_dart_perguntas_versao ON dart_perguntas(versao_id, status, ordem)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS dart_alternativas (
                id TEXT PRIMARY KEY,
                pergunta_id TEXT NOT NULL,
                texto TEXT NOT NULL,
                perfil TEXT NOT NULL,
                ordem INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_dart_alt_pergunta ON dart_alternativas(pergunta_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS dart_avaliacoes (
                id TEXT PRIMARY KEY,
                avaliando_id TEXT NOT NULL,
                solicitante_id TEXT DEFAULT NULL,
                token TEXT NOT NULL UNIQUE,
                versao_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente',
                data_inicio TEXT DEFAULT NULL,
                data_conclusao TEXT DEFAULT NULL,
                data_expiracao TEXT DEFAULT NULL,
                pontuacao_analista INTEGER DEFAULT 0,
                pontuacao_executor INTEGER DEFAULT 0,
                pontuacao_planejador INTEGER DEFAULT 0,
                pontuacao_comunicador INTEGER DEFAULT 0,
                pontuacao_total INTEGER DEFAULT 0,
                perfil_principal TEXT DEFAULT '',
                segundo_perfil TEXT DEFAULT '',
                terceiro_perfil TEXT DEFAULT '',
                quarto_perfil TEXT DEFAULT '',
                combinacao TEXT DEFAULT '',
                codenome TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        _safe_add_column(c, 'dart_avaliacoes', 'created_at', "created_at TEXT NOT NULL DEFAULT ''")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dart_avaliacoes_avaliando ON dart_avaliacoes(avaliando_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dart_avaliacoes_status ON dart_avaliacoes(status)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS dart_respostas (
                id TEXT PRIMARY KEY,
                avaliacao_id TEXT NOT NULL,
                pergunta_id TEXT NOT NULL,
                alternativa_id TEXT DEFAULT NULL,
                perfil_da_alternativa TEXT NOT NULL,
                pontuacao INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(avaliacao_id, pergunta_id)
            )
        """)
        _safe_add_column(c, 'dart_respostas', 'alternativa_id', "alternativa_id TEXT DEFAULT NULL")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dart_respostas_avaliacao ON dart_respostas(avaliacao_id)")

        # Seed idempotente da versão v1 + 25 perguntas
        from dart_data import DART_QUESTIONS_V1, DART_PERFIS
        _seed_dart_v1(c)

        conn.commit()
        print("Banco de dados inicializado.")

    except Exception:
        conn.rollback()
        raise

    finally:
        c.close()
        conn.close()
