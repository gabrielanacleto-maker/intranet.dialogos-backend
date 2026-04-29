import sqlite3
from pathlib import Path
import datetime
from auth import hash_password

import os

DB_PATH = Path(os.getenv("DB_PATH", "dialogos.db"))


# Conexão global persistente — evita "Cannot operate on a closed database"
_conn = None

def get_connection():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn

def get_db():
    """Dependency do FastAPI — retorna sempre a mesma conexão aberta."""
    yield get_connection()

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # ✅ SAFE MIGRATIONS - só adiciona se faltar
    new_columns = [
        ('users', 'photo_url', "TEXT DEFAULT ''"),
        ('posts', 'author_photo_url', "TEXT DEFAULT ''"),
        ('users', 'hire_date', "TEXT DEFAULT ''"),
        ('users', 'org_position', "TEXT DEFAULT 'colaborador'"),
        ('users', 'is_orcoma', "INTEGER DEFAULT 0"),
        ('users', 'is_ouvidor', "INTEGER DEFAULT 0"),
        ('ouvidoria', 'responses', "TEXT DEFAULT '[]'"),
        ('ouvidoria', 'category', "TEXT DEFAULT ''"),
        ('posts', 'comunicado_tipo', "TEXT DEFAULT NULL"),        
        ('social_rooms', 'is_private', "INTEGER DEFAULT 0"),
    ]
    for table, column, col_def in new_columns:
        try:
            c.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in c.fetchall()]
            if column not in columns:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        except Exception as e:
            print(f"Migration skip {table}.{column}: {e}")
    
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        key TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        initials TEXT NOT NULL,
        role TEXT DEFAULT '',
        dept TEXT DEFAULT '',
        level TEXT DEFAULT 'dourado',
        color TEXT DEFAULT 'av-gold',
        access_level INTEGER DEFAULT 0,
        is_admin INTEGER DEFAULT 0,
        is_admin_user INTEGER DEFAULT 0,
        is_rh INTEGER DEFAULT 0,
        is_ouvidor INTEGER DEFAULT 0,
        points INTEGER DEFAULT 100,
        password_hash TEXT NOT NULL,
        password_changed INTEGER DEFAULT 0,
        photo_url TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    feed TEXT DEFAULT 'feed',
    author_key TEXT,
    author_name TEXT,
    author_initials TEXT,
    author_color TEXT,
    author_photo_url TEXT DEFAULT '',
    text TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    embed_url TEXT DEFAULT '',
    access_level TEXT DEFAULT 'all',
    comunicado_tipo TEXT DEFAULT NULL,
    pinned INTEGER DEFAULT 0,
    likes TEXT DEFAULT '[]',
    comments TEXT DEFAULT '[]',
    created_at TEXT
);





    CREATE TABLE IF NOT EXISTS security_logs (
        id TEXT PRIMARY KEY,
        actor_key TEXT,
        target_key TEXT,
        action_type TEXT,
        details TEXT DEFAULT '',
        created_at TEXT
    );

    
    CREATE TABLE IF NOT EXISTS mural_items (
        id TEXT PRIMARY KEY,
        tag TEXT DEFAULT 'Novidades',
        title TEXT,
        subtitle TEXT DEFAULT '',
        content TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS folders (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon TEXT DEFAULT '📁',
        level TEXT DEFAULT 'all',
        drive_link TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS folder_files (
        id TEXT PRIMARY KEY,
        folder_id TEXT,
        name TEXT,
        url TEXT,
        size INTEGER DEFAULT 0,
        mime_type TEXT DEFAULT '',
        uploaded_by TEXT DEFAULT '',
        created_at TEXT,
        FOREIGN KEY (folder_id) REFERENCES folders(id)
    );

    CREATE TABLE IF NOT EXISTS ouvidoria (
        id TEXT PRIMARY KEY,
        author_key TEXT,
        author_name TEXT,
        category TEXT DEFAULT '',
        text TEXT DEFAULT '',
        status TEXT DEFAULT 'aberta',
        responses TEXT DEFAULT '[]',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        sender_key TEXT NOT NULL,
        sender_name TEXT NOT NULL,
        sender_photo TEXT DEFAULT '',
        sender_initials TEXT DEFAULT '',
        sender_color TEXT DEFAULT 'av-gold',
        text TEXT DEFAULT '',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS social_rooms (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_private INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS social_room_files (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        size INTEGER DEFAULT 0,
        mime_type TEXT DEFAULT '',
        uploaded_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (room_id) REFERENCES social_rooms(id)
    );

    CREATE TABLE IF NOT EXISTS social_room_members (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL,
        user_key TEXT NOT NULL,
        added_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(room_id, user_key),
        FOREIGN KEY (room_id) REFERENCES social_rooms(id),
        FOREIGN KEY (user_key) REFERENCES users(key)
    );

    CREATE TABLE IF NOT EXISTS organogram (
        id TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        parent_key TEXT DEFAULT '',
        position_order INTEGER DEFAULT 0,
        org_tier TEXT DEFAULT 'colaborador'
    );

    CREATE TABLE IF NOT EXISTS mood_history (
        id TEXT PRIMARY KEY,
        user_key TEXT,
        mood TEXT,
        intensity INTEGER DEFAULT 3,
        reason TEXT DEFAULT '',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS price_doctors (
        id TEXT PRIMARY KEY,
        folder_id TEXT NOT NULL,
        name TEXT NOT NULL,
        specialty TEXT DEFAULT '',
        crm TEXT DEFAULT '',
        rqe TEXT DEFAULT '',
        position_order INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY (folder_id) REFERENCES folders(id)
    );

    CREATE TABLE IF NOT EXISTS price_procedures (
        id TEXT PRIMARY KEY,
        doctor_id TEXT NOT NULL,
        name TEXT NOT NULL,
        value_cash REAL DEFAULT 0,
        value_card_pix REAL DEFAULT 0,
        value_bradesco REAL DEFAULT 0,
        value_brv REAL DEFAULT 0,
        value_prefeitura REAL DEFAULT 0,
        position_order INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY (doctor_id) REFERENCES price_doctors(id)
    );

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
        created_by TEXT,
        created_at TEXT
    );

                    CREATE TABLE IF NOT EXISTS user_points (
        id TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        points INTEGER DEFAULT 0,
        reason TEXT DEFAULT '',
        action_type TEXT DEFAULT '',
        created_at TEXT,
        FOREIGN KEY (user_key) REFERENCES users(key)
    );

    CREATE TABLE IF NOT EXISTS user_badges (
        id TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        badge_type TEXT NOT NULL,
        badge_name TEXT NOT NULL,
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '⭐',
        earned_at TEXT,
        FOREIGN KEY (user_key) REFERENCES users(key),
        UNIQUE(user_key, badge_type)
    );

    CREATE TABLE IF NOT EXISTS monthly_ranking (
        id TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        points INTEGER DEFAULT 0,
        position INTEGER DEFAULT 0,
        month TEXT NOT NULL,
        year INTEGER NOT NULL,
        updated_at TEXT,
        FOREIGN KEY (user_key) REFERENCES users(key),
        UNIQUE(user_key, month, year)
    );

    CREATE TABLE IF NOT EXISTS user_achievements (
        id TEXT PRIMARY KEY,
        user_key TEXT NOT NULL,
        achievement_type TEXT NOT NULL,
        achievement_name TEXT NOT NULL,
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '🏆',
        unlocked_at TEXT,
        FOREIGN KEY (user_key) REFERENCES users(key),
        UNIQUE(user_key, achievement_type)
    );
                """)

    # Seed Gabriel (Super Admin - Nível 3)
    existing = c.execute("SELECT 1 FROM users WHERE key='gabriel'").fetchone()
    if not existing:
        c.execute("""INSERT INTO users
            (key, name, initials, role, dept, level, color, access_level,
             is_admin, is_admin_user, is_rh, is_ouvidor, points, password_hash, password_changed)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('gabriel', 'Gabriel Anacleto de Souza Cruz', 'GA',
             'Auxiliar Financeiro Jr', 'Financeiro & System Adm',
             'diamante', 'av-gold', 3, 1, 0, 0, 0, 100,
             hash_password('dialogos@2025'), 1)
        )

    # Seed Tairla (Admin User - Nível 2)
    existing2 = c.execute("SELECT 1 FROM users WHERE key='tairla'").fetchone()
    if not existing2:
        c.execute("""INSERT INTO users
            (key, name, initials, role, dept, level, color, access_level,
             is_admin, is_admin_user, is_rh, is_ouvidor, points, password_hash, password_changed)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('tairla', 'Tairla Andrade Carvalho Mascarenhas', 'TA',
             'Diretora', 'Administrativo & User Adm',
             'diamante', 'av-teal', 2, 0, 1, 1, 0, 100,
             hash_password('trocar123'), 0)
        )

    # Seed Malu (Funcionário - Nível 1)
    existing3 = c.execute("SELECT 1 FROM users WHERE key='malu'").fetchone()
    if not existing3:
        c.execute("""INSERT INTO users
            (key, name, initials, role, dept, level, color, access_level,
             is_admin, is_admin_user, is_rh, is_ouvidor, points, password_hash, password_changed)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('malu', 'Maria Luiza Alves Macedo', 'MA',
             'Líder', 'Administrativo',
             'platina', 'av-blue', 1, 0, 0, 0, 1, 100,
             hash_password('trocar123'), 0)
        )

    # Seed folders default
    folders_count = c.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
    if folders_count == 0:
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
        c.executemany("INSERT INTO folders (id, name, icon, level, drive_link) VALUES (?,?,?,?,?)", default_folders)

    # Seed sala geral
    social_count = c.execute("SELECT COUNT(*) FROM social_rooms").fetchone()[0]
    if social_count == 0:
        import uuid
        room_id = str(uuid.uuid4())
        c.execute("""INSERT INTO social_rooms (id, name, description, created_by, created_at)
            VALUES (?,?,?,?,?)""",
            (room_id, 'Sala Geral', 'Canal principal da clínica para alinhamentos rápidos.', 'gabriel', '2026-04-22T00:00:00')
        )
        c.execute("""INSERT OR IGNORE INTO social_room_members (id, room_id, user_key, added_by, created_at)
            VALUES (?,?,?,?,?)""",
            (str(uuid.uuid4()), room_id, 'gabriel', 'gabriel', '2026-04-22T00:00:00')
        )

    conn.commit()
    print("✅ Banco de dados inicializado.")