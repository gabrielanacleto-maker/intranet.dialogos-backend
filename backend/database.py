import psycopg2
import psycopg2.extras
import os
import uuid

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

def init_db():
    conn = psycopg2.connect(DB_URL)
    c = conn.cursor()

    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS about_me TEXT DEFAULT ''")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_diretor INTEGER DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_leader INTEGER DEFAULT 0")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS video_url TEXT DEFAULT ''")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_role TEXT DEFAULT ''")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_is_rh INTEGER DEFAULT 0")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_is_admin INTEGER DEFAULT 0")

        # ── NOVAS TABELAS ──────────────────────────────────────────────────────
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_diretor INTEGER DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_leader INTEGER DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_orcoma INTEGER DEFAULT 0")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hire_date TEXT DEFAULT ''")  
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS org_position TEXT DEFAULT 'colaborador'")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS manager_key TEXT DEFAULT NULL")
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS nivel_dourado INTEGER DEFAULT 0")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS video_url TEXT DEFAULT ''")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_role TEXT DEFAULT ''")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_is_rh INTEGER DEFAULT 0")
        c.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS author_is_admin INTEGER DEFAULT 0")

        # post_views table
        c.execute("""
            CREATE TABLE IF NOT EXISTS post_views (
                id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL,
                post_id TEXT NOT NULL,
                viewed_at TEXT NOT NULL,
                UNIQUE(user_key, post_id)
            )
        """)

        # evaluations table
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

        # presence table
        c.execute("""
            CREATE TABLE IF NOT EXISTS presence (
                user_key TEXT PRIMARY KEY,
                is_online INTEGER DEFAULT 0,
                last_seen TEXT,
                last_activity TEXT
            )
        """)

        # colleague_feedback table (LinkedIn-style)
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

        # audit_log table
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

        # calendar_events table
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

        # ADD column nivelDourado to folders  
        try:
            c.execute("ALTER TABLE folders ADD COLUMN IF NOT EXISTS nivel_dourado INTEGER DEFAULT 0")
        except:
            pass

        # ADD column created_by to folders
        try:
            c.execute("ALTER TABLE folders ADD COLUMN IF NOT EXISTS created_by TEXT DEFAULT ''")
        except:
            pass

        # Ensure calendar_events has user_key column
        try:
            c.execute("ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS user_key TEXT DEFAULT ''")
            c.execute("UPDATE calendar_events SET user_key = created_by WHERE user_key = '' OR user_key IS NULL")
        except:
            pass

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
                (str(uuid.uuid4()), 'POPs Gerais', '📋', 'all', ''),
                (str(uuid.uuid4()), 'POPs Financeiros', '📊', 'platina', ''),
                (str(uuid.uuid4()), 'Contratos & Relatórios', '📑', 'diamante', ''),
                (str(uuid.uuid4()), 'Tabela de Preços', '💲', 'dourado', ''),
                (str(uuid.uuid4()), 'Organograma', '🏢', 'all', ''),
                (str(uuid.uuid4()), 'Recursos Humanos', '👥', 'rh', ''),
                (str(uuid.uuid4()), 'Treinamentos', '🎓', 'all', ''),
                (str(uuid.uuid4()), 'Gestão de Acessos', '🔐', 'diamante', ''),
            ]
            c.executemany(
                "INSERT INTO folders (id, name, icon, level, drive_link) VALUES (%s,%s,%s,%s,%s)",
                default_folders
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

        # ── TAREFAS: add new columns ──────────────────────────────────────────
        try:
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pendente'")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS custom_status TEXT DEFAULT NULL")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS prioridade TEXT DEFAULT 'media'")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS tipo_tarefa TEXT DEFAULT 'tarefa'")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS recorrencia TEXT DEFAULT 'nenhuma'")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS duration_seconds INTEGER DEFAULT 0")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS started_at TEXT DEFAULT NULL")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS ended_at TEXT DEFAULT NULL")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS delay_reason TEXT DEFAULT NULL")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS delayed_at TEXT DEFAULT NULL")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS paused_seconds INTEGER DEFAULT 0")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS delegated_by TEXT DEFAULT NULL")
            c.execute("ALTER TABLE tarefas ADD COLUMN IF NOT EXISTS concluida_em TEXT DEFAULT NULL")
        except:
            pass

        # ── TASK COMMENTS ──────────────────────────────────────────────────────
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

        # ── TASK HISTORY ───────────────────────────────────────────────────────
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

        # ── OBJETIVOS GAMIFICADOS ───────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS objetivos_def (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                descricao TEXT DEFAULT '',
                categoria TEXT NOT NULL DEFAULT 'tarefas',
                recompensa_dcoins INTEGER NOT NULL DEFAULT 10,
                meta_valor INTEGER NOT NULL DEFAULT 1,
                meta_unidade TEXT NOT NULL DEFAULT 'tarefas',
                periodicidade TEXT NOT NULL DEFAULT 'diaria',
                tipo_progresso TEXT NOT NULL DEFAULT 'incremental',
                icone TEXT NOT NULL DEFAULT 'ti-star',
                ativo INTEGER NOT NULL DEFAULT 1,
                owner_key TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS objetivos_progress (
                id TEXT PRIMARY KEY,
                objetivo_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                progresso_atual INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pendente',
                ultimo_reset TEXT,
                ultima_atualizacao TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (objetivo_id) REFERENCES objetivos_def(id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS objetivos_audit_log (
                id TEXT PRIMARY KEY,
                objetivo_id TEXT NOT NULL,
                user_key TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT DEFAULT '',
                ip_address TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (objetivo_id) REFERENCES objetivos_def(id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS objetivos_streaks (
                id TEXT PRIMARY KEY,
                user_key TEXT NOT NULL UNIQUE,
                current_streak INTEGER NOT NULL DEFAULT 0,
                max_streak INTEGER NOT NULL DEFAULT 0,
                last_date TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        print("✅ Banco de dados inicializado.")

    except Exception:
        conn.rollback()
        raise

    finally:
        c.close()
        conn.close()
