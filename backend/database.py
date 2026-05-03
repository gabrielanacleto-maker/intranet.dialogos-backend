import psycopg2
import psycopg2.extras
import os

from auth import hash_password

from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD")
DEFAULT_USER_PASSWORD = os.getenv("DEFAULT_USER_PASSWORD")

if not DB_URL:
    raise ValueError("DATABASE_URL não configurada")

if not ADMIN_DEFAULT_PASSWORD or not DEFAULT_USER_PASSWORD:
    raise ValueError("Senhas padrão não configuradas")


# Conexão global persistente — evita "Cannot operate on a closed database"
def get_connection():
    global _conn
    try:
        if _conn is None or _conn.closed:
            raise Exception("reconectar")
        # Testa se a conexão está viva
        _conn.cursor().execute("SELECT 1")
    except Exception:
        _conn = psycopg2.connect(DB_URL)
        _conn.autocommit = False
    return _conn

def get_db():
    """Dependency do FastAPI — retorna sempre a mesma conexão aberta."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()

def init_db():
    conn = get_connection()
    c = conn.cursor()

    try:
        # Seed Gabriel
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

        # Seed Tairla
        c.execute("SELECT 1 FROM users WHERE key=%s", ('tairla',))
        if not c.fetchone():
            c.execute("""INSERT INTO users
                (key, name, initials, role, dept, level, color, access_level,
                 is_admin, is_admin_user, is_rh, is_ouvidor, points, password_hash, password_changed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                ('tairla', 'Tairla Andrade Carvalho Mascarenhas', 'TA',
                 'Diretora', 'Administrativo & User Adm',
                 'diamante', 'av-teal', 2, 0, 1, 1, 0, 100,
                 hash_password(DEFAULT_USER_PASSWORD), 0)
            )

        # Seed Malu
        c.execute("SELECT 1 FROM users WHERE key=%s", ('malu',))
        if not c.fetchone():
            c.execute("""INSERT INTO users
                (key, name, initials, role, dept, level, color, access_level,
                 is_admin, is_admin_user, is_rh, is_ouvidor, points, password_hash, password_changed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                ('malu', 'Maria Luiza Alves Macedo', 'MA',
                 'Líder', 'Administrativo',
                 'platina', 'av-blue', 1, 0, 0, 0, 1, 100,
                 hash_password(DEFAULT_USER_PASSWORD), 0)
            )

        # Seed folders
        c.execute("SELECT COUNT(*) FROM folders")
        if c.fetchone()[0] == 0:
            import uuid
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

        # Seed sala geral
        c.execute("SELECT COUNT(*) FROM social_rooms")
        if c.fetchone()[0] == 0:
            import uuid
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

        conn.commit()
        print("✅ Banco de dados inicializado.")

    except Exception:
        conn.rollback()
        raise

    finally:
        c.close()