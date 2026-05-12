from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import os, uuid, shutil, datetime, json, re
from pathlib import Path
from pydantic import BaseModel
from typing import Optional, List

# ═════════════════════════════════════════════════════════════════════════════
# IMPORTS LOCAIS
# ═════════════════════════════════════════════════════════════════════════════
from models import *
from database import get_db, init_db, get_db_context
from auth import create_token, verify_token, hash_password, check_password
import cloudinary
import cloudinary.uploader

# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES E CONSTANTES
# ═════════════════════════════════════════════════════════════════════════════
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Variáveis de ambiente (NUNCA expose no código)
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")

# CORS seguro
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")

# Constantes de negócio
MAX_FILE_SIZE_FOLDER = 50 * 1024 * 1024  # 50MB
MAX_FILE_SIZE_POST = 10 * 1024 * 1024    # 10MB
MAX_FEEDBACK_CHARS = 2000
FEEDBACK_RATE_LIMIT_HOURS = 6
RANK_THRESHOLDS = [
    (0, 49, "Aspirante"), (50, 149, "Motivado"), (150, 299, "Engajado"),
    (300, 499, "Competidor"), (500, 699, "Destaque"), (700, 899, "Referência"),
    (900, 999, "Elite"), (1000, 9999999, "Lenda")
]
ALLOWED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# ═════════════════════════════════════════════════════════════════════════════
# INICIALIZAÇÃO
# ═════════════════════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET
)

app = FastAPI(title="Intranet Diálogos API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

security = HTTPBearer(auto_error=False)

# ═════════════════════════════════════════════════════════════════════════════
# HELPERS E UTILIDADES
# ═════════════════════════════════════════════════════════════════════════════

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token ausente")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    with get_db_context() as db:
        user = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        return dict(user)

def require_level(min_level: int):
    def checker(user=Depends(get_current_user)):
        if user["access_level"] < min_level:
            raise HTTPException(status_code=403, detail="Acesso negado")
        return user
    return checker

def require_admin(user: dict):
    if not (user.get("is_admin") or user.get("is_admin_user")):
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas admins.")

def can_evaluate(user: dict) -> bool:
    return bool(user.get('is_admin') or user.get('is_admin_user') or user.get('is_rh') or user.get('is_ouvidor'))

def log_action(db, actor_key, target_key, action_type, details=""):
    db.execute(
        "INSERT INTO security_logs (id, actor_key, target_key, action_type, details, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), actor_key, target_key, action_type, details, datetime.datetime.utcnow().isoformat())
    )

def extract_room_id(channel_value: str | None):
    if not channel_value or not channel_value.startswith("sala_"):
        return None
    return channel_value[5:]

def extract_mentions(text: str) -> list:
    return re.findall(r'@([A-Za-z0-9_]+)', text or '')

def sanitize_text(text: str, max_chars: int = MAX_FEEDBACK_CHARS) -> str:
    """Remove padrões perigosos de HTML/JS e normalize."""
    if not text:
        return ""
    dangerous = [
        r'<script[\s\S]*?>[\s\S]*?</script>', r'<iframe[\s\S]*?>', r'javascript:', r'onerror\s*=',
        r'onclick\s*=', r'onload\s*=', r'eval\s*\(', r'window\.location'
    ]
    for pattern in dangerous:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()[:max_chars]

def get_rank(xp: int) -> str:
    return next((r[2] for r in RANK_THRESHOLDS if r[0] <= xp <= r[1]), "Aspirante")

def can_access_social_room(db, room_id: str, user):
    room = db.execute("SELECT * FROM social_rooms WHERE id=%s", (room_id,)).fetchone()
    if not room:
        return False, None
    room_dict = dict(room)
    if not room_dict.get("is_private"):
        return True, room_dict
    if user["is_admin"] or user["is_admin_user"]:
        return True, room_dict
    member = db.execute("SELECT 1 FROM social_room_members WHERE room_id=%s AND user_key=%s", (room_id, user["key"])).fetchone()
    return bool(member), room_dict

# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM: NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════

def ensure_notifications_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, message TEXT NOT NULL, type TEXT NOT NULL,
        target_user_key TEXT NULL, audience TEXT DEFAULT 'personal',
        sender_key TEXT NULL, sender_name TEXT NULL, reference_id TEXT NULL,
        play_sound BOOLEAN DEFAULT FALSE, is_read BOOLEAN DEFAULT FALSE, created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_notif_target ON notifications(target_user_key)")

def notify(db, *, title: str, message: str, ntype: str, target_user_key: str = None,
           audience: str = None, sender_key: str = None, sender_name: str = None,
           reference_id: str = None, play_sound: bool = False):
    ensure_notifications_table(db)
    db.execute("""INSERT INTO notifications
        (id, title, message, type, target_user_key, audience, sender_key, sender_name, reference_id, play_sound, is_read, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), title, message, ntype, target_user_key, audience or ('personal' if target_user_key else 'all'),
         sender_key, sender_name, reference_id, play_sound, False, datetime.datetime.utcnow().isoformat()))

# ═════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/login")
def login(body: LoginRequest, db=Depends(get_db)):
    user = db.execute("SELECT * FROM users WHERE key=%s", (body.key.lower(),)).fetchone()
    if not user or not check_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
    token = create_token({"sub": user["key"], "level": user["access_level"]})
    return {
        "token": token,
        "must_change_password": not user["password_changed"],
        "user": {k: user[k] for k in ["key", "name", "initials", "role", "dept", "level", "color", 
                 "access_level", "is_admin", "is_admin_user", "is_rh", "is_ouvidor", "points", "photo_url"]}
    }

@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not check_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")
    db.execute("UPDATE users SET password_hash=%s, password_changed=1 WHERE key=%s",
               (hash_password(body.new_password), user["key"]))
    db.commit()
    log_action(db, user["key"], user["key"], "Troca de Senha", "Usuário alterou própria senha")
    return {"ok": True}

# ═════════════════════════════════════════════════════════════════════════════
# USERS ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/users")
def list_users(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password_hash", None)
        if user["access_level"] < 2:
            d.pop("password_changed", None)
        result.append(d)
    return result

@app.post("/api/users")
def create_user(body: CreateUserRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    key = body.key.lower().strip()
    if db.execute("SELECT 1 FROM users WHERE key=%s", (key,)).fetchone():
        raise HTTPException(status_code=400, detail="Usuário já existe.")
    db.execute("""INSERT INTO users
        (key, name, initials, role, dept, level, color, access_level, is_admin, is_admin_user, is_rh, 
         is_ouvidor, points, password_hash, password_changed, photo_url)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s)""",
        (key, body.name, body.initials, body.role, body.dept, body.level, body.color, body.access_level,
         int(body.is_admin), int(body.is_admin_user), int(body.is_rh), int(body.is_ouvidor), body.points,
         hash_password(body.password), ""))
    db.commit()
    log_action(db, user["key"], key, "Criação de Usuário", f"Criou usuário {body.name}")
    return {"ok": True}

@app.put("/api/users/{target_key}")
def update_user(target_key: str, body: UpdateUserRequest, user=Depends(get_current_user), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if user["key"] != target_key and user["access_level"] < 2:
        raise HTTPException(status_code=403, detail="Sem permissão.")
    if user["access_level"] == 2 and target["access_level"] >= 2:
        raise HTTPException(status_code=403, detail="Você não pode editar admins.")
    db.execute("""UPDATE users SET name=%s, initials=%s, role=%s, dept=%s, level=%s, color=%s, 
        access_level=%s, is_admin=%s, is_admin_user=%s, is_rh=%s, is_ouvidor=%s, points=%s WHERE key=%s""",
        (body.name, body.initials, body.role, body.dept, body.level, body.color, body.access_level,
         int(body.is_admin), int(body.is_admin_user), int(body.is_rh), int(body.is_ouvidor), body.points, target_key))
    db.commit()
    return {"ok": True}

@app.post("/api/users/{target_key}/reset-password")
def reset_password(target_key: str, body: ResetPasswordRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if user["access_level"] == 2 and target["access_level"] >= 2:
        raise HTTPException(status_code=403, detail="Você não pode resetar admins do mesmo nível.")
    db.execute("UPDATE users SET password_hash=%s, password_changed=0 WHERE key=%s",
               (hash_password(body.new_password), target_key))
    db.commit()
    log_action(db, user["key"], target_key, "Reset de Senha", f"{user['name']} resetou senha de {target['name']}")
    return {"ok": True}

@app.delete("/api/users/{target_key}")
def delete_user(target_key: str, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404)
    if user["access_level"] < 3 and target["access_level"] >= user["access_level"]:
        raise HTTPException(status_code=403, detail="Permissão insuficiente.")
    db.execute("DELETE FROM users WHERE key=%s", (target_key,))
    db.commit()
    log_action(db, user["key"], target_key, "Exclusão de Usuário", f"Removeu {target['name']}")
    return {"ok": True}

@app.post("/api/users/me/photo")
def upload_photo(file: UploadFile = File(...), user=Depends(get_current_user), db=Depends(get_db)):
    if Path(file.filename or "").suffix.lower() not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail="Formato inválido. Use JPG, PNG ou WEBP.")
    result = cloudinary.uploader.upload(file.file, folder="dialogos/fotos", 
                                        public_id=f"photo_{user['key']}", overwrite=True)
    db.execute("UPDATE users SET photo_url=%s WHERE key=%s", (result["secure_url"], user["key"]))
    db.commit()
    return {"url": result["secure_url"]}

# ═════════════════════════════════════════════════════════════════════════════
# POSTS ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/posts")
def get_posts(feed: str = "feed", user=Depends(get_current_user), db=Depends(get_db)):
    room_id = extract_room_id(feed)
    if room_id:
        allowed, _ = can_access_social_room(db, room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    rows = db.execute("SELECT * FROM posts WHERE feed=%s ORDER BY pinned DESC, created_at DESC", (feed,)).fetchall()
    return [{"id": dict(r)["id"], "text": dict(r)["text"], "likes": json.loads(dict(r).get("likes") or "[]"), 
             "comments": json.loads(dict(r).get("comments") or "[]"), **{k: dict(r)[k] for k in dict(r).keys() if k not in ["likes", "comments"]}} 
            for r in rows]

@app.post("/api/posts")
def create_post(body: CreatePostRequest, user=Depends(get_current_user), db=Depends(get_db)):
    room_id = extract_room_id(body.feed)
    if room_id:
        allowed, _ = can_access_social_room(db, room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    if body.feed == "novidades" and not (user["is_admin"] or user["is_admin_user"] or user["is_rh"] or user["level"] in ["platina", "diamante"]):
        raise HTTPException(status_code=403, detail="Sem permissão para publicar.")
    post_id = str(uuid.uuid4())
    db.execute("""INSERT INTO posts
        (id, feed, author_key, author_name, author_initials, author_color, author_photo_url, text, 
         image_url, embed_url, access_level, comunicado_tipo, pinned, likes, comments, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (post_id, body.feed, user["key"], user["name"], user["initials"], user["color"], user.get("photo_url", ""),
         body.text, body.image_url or "", body.embed_url or "", body.access_level, body.comunicado_tipo, 0, '[]', '[]',
         datetime.datetime.utcnow().isoformat()))
    notify(db, title="📢 Nova publicação" if body.comunicado_tipo else "📋 Novo post",
           message=f"{user['name']}: {(body.text or '')[:80]}", ntype="post",
           audience=body.access_level if body.access_level not in ("all", "") else "all",
           sender_key=user["key"], sender_name=user["name"], reference_id=post_id)
    for mention_key in extract_mentions(body.text):
        target = db.execute("SELECT key FROM users WHERE key=%s", (mention_key,)).fetchone()
        if target and target["key"] != user["key"]:
            notify(db, title="👋 Menção", message=f"{user['name']} mencionou você",
                   ntype="mention", target_user_key=target["key"], sender_key=user["key"],
                   sender_name=user["name"], reference_id=post_id, play_sound=True)
    db.commit()
    return {"ok": True, "id": post_id}

@app.post("/api/posts/upload-image")
def upload_post_image(file: UploadFile = File(...), user=Depends(get_current_user)):
    if file.size and file.size > MAX_FILE_SIZE_POST:
        raise HTTPException(status_code=400, detail="Imagem muito grande (máx 10MB)")
    if Path(file.filename).suffix.lower() not in ALLOWED_IMAGE_FORMATS:
        raise HTTPException(status_code=400, detail="Formato inválido")
    result = cloudinary.uploader.upload(file.file, folder="dialogos/posts", resource_type="image")
    return {"url": result["secure_url"]}

@app.delete("/api/posts/{post_id}")
def delete_post(post_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    if post["author_key"] != user["key"] and not (user["is_admin"] or user["is_admin_user"]):
        raise HTTPException(status_code=403)
    db.execute("DELETE FROM posts WHERE id=%s", (post_id,))
    db.commit()
    return {"ok": True}

@app.post("/api/posts/{post_id}/pin")
def pin_post(post_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    new_pin = 0 if post["pinned"] else 1
    db.execute("UPDATE posts SET pinned=%s WHERE id=%s", (new_pin, post_id))
    db.commit()
    return {"pinned": bool(new_pin)}

@app.post("/api/posts/{post_id}/like")
def toggle_like(post_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    likes = json.loads(post["likes"] or "[]")
    if user["key"] in likes:
        likes.remove(user["key"])
    else:
        likes.append(user["key"])
    db.execute("UPDATE posts SET likes=%s WHERE id=%s", (json.dumps(likes), post_id))
    db.commit()
    return {"likes": likes}

@app.post("/api/posts/{post_id}/comment")
def add_comment(post_id: str, body: CommentRequest, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    comments = json.loads(post["comments"] or "[]")
    comment = {
        "id": str(uuid.uuid4())[:8], "author_key": user["key"], "author_name": user["name"],
        "author_initials": user["initials"], "author_color": user.get("color", "av-gold"),
        "author_photo_url": user.get("photo_url", ""), "text": body.text,
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    comments.append(comment)
    db.execute("UPDATE posts SET comments=%s WHERE id=%s", (json.dumps(comments), post_id))
    if post["author_key"] and post["author_key"] != user["key"]:
        notify(db, title="💬 Novo comentário", message=f"{user['name']}: {(body.text or '')[:80]}",
               ntype="comment", target_user_key=post["author_key"], sender_key=user["key"],
               sender_name=user["name"], reference_id=post_id, play_sound=True)
    for mention_key in extract_mentions(body.text):
        target = db.execute("SELECT key FROM users WHERE key=%s", (mention_key,)).fetchone()
        if target and target["key"] != user["key"]:
            notify(db, title="👋 Menção", message=f"{user['name']} mencionou você",
                   ntype="mention", target_user_key=target["key"], sender_key=user["key"],
                   sender_name=user["name"], reference_id=post_id, play_sound=True)
    db.commit()
    return {"comments": comments}

# ═════════════════════════════════════════════════════════════════════════════
# OUTROS ENDPOINTS (RESUMIDOS)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/security-logs")
def get_logs(user=Depends(require_level(2)), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM security_logs ORDER BY created_at DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/notifications")
def get_notifications(user=Depends(get_current_user), db=Depends(get_db)):
    ensure_notifications_table(db)
    rows = db.execute(
        "SELECT * FROM notifications WHERE target_user_key=%s OR audience='all' OR audience=%s ORDER BY created_at DESC LIMIT 40",
        (user["key"], user.get("dept", ""))).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/notifications/{notif_id}/read")
def mark_read(notif_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    db.execute("UPDATE notifications SET is_read=TRUE WHERE id=%s AND (target_user_key=%s OR audience='all')",
               (notif_id, user["key"]))
    return {"ok": True}

@app.get("/api/ranking")
def get_ranking(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT key, name, initials, color, level, points FROM users ORDER BY points DESC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/gamificacao/add-points")
def add_points(user_key: str, points: int, reason: str, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT points FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404)
    new_total = (target["points"] or 0) + points
    db.execute("INSERT INTO user_points (id, user_key, points, reason, created_at) VALUES (%s,%s,%s,%s,%s)",
               (str(uuid.uuid4()), user_key, points, reason, datetime.datetime.utcnow().isoformat()))
    db.execute("UPDATE users SET points=%s WHERE key=%s", (new_total, user_key))
    db.commit()
    return {"ok": True, "new_total": new_total}

# Endpoints de feedbacks, mural, folders, social rooms podem ser adicionados conforme necessário
# Remova endpoints não críticos para manter o arquivo enxuto