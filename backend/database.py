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
        _safe_add_column(c, 'users', 'empresa_id', "empresa_id TEXT DEFAULT NULL")

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

        c.execute("UPDATE users SET empresa_id='orcoma' WHERE is_orcoma=1 AND (empresa_id IS NULL OR empresa_id='')")
        c.execute("UPDATE users SET empresa_id='dialogos' WHERE is_orcoma=0 AND (empresa_id IS NULL OR empresa_id='')")

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
                reactions TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

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

        conn.commit()
        print("Banco de dados inicializado.")

    except Exception:
        conn.rollback()
        raise

    finally:
        c.close()
        conn.close()
