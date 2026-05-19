from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, status, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import os, uuid, shutil, datetime, json, re, time
from urllib.parse import urlparse
from pathlib import Path

from pydantic import BaseModel

from models import *
from database import get_db, init_db, get_db_context
from auth import create_token, verify_token, hash_password, check_password

import cloudinary
import cloudinary.uploader


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024
TRUSTED_EMBED_DOMAINS = {"instagram.com", "tiktok.com", "youtube.com", "youtu.be", "twitter.com", "x.com", "spotify.com", "wa.me", "whatsapp.com"}

# Simple in-memory rate limiting
_upload_limits = {}

def _check_upload_rate_limit(user_key: str):
    now = time.time()
    minute = int(now / 60)
    key = f"{user_key}:{minute}"
    count = _upload_limits.get(key, 0)
    if count >= 10:
        raise HTTPException(status_code=429, detail="Limite de uploads excedido. Tente novamente em 1 minuto.")
    _upload_limits[key] = count + 1

def _sanitize_text(text: str) -> str:
    if not text:
        return ""
    dangerous = [
        r'<script[\s\S]*?>[\s\S]*?</script>', r'<iframe[\s\S]*?>', r'<object[\s\S]*?>',
        r'<embed[\s\S]*?>', r'<svg[\s\S]*?>', r'<style[\s\S]*?>',
        r'javascript:', r'data:', r'vbscript:',
        r'onerror\s*=', r'onclick\s*=', r'onload\s*=', r'onmouseover\s*=',
        r'onsubmit\s*=', r'onfocus\s*=', r'onchange\s*=', r'oninput\s*=',
        r'eval\s*\(', r'Function\s*\(', r'document\.cookie',
        r'window\.location', r'innerHTML', r'outerHTML',
        r'fetch\s*\(', r'XMLHttpRequest', r'new\s+Function',
        r'alert\s*\(', r'prompt\s*\(', r'confirm\s*\(',
    ]
    for pattern in dangerous:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()[:5000]

def _validate_embed_url(url: str) -> str:
    if not url:
        return url
    try:
        u = url.strip()
        parsed = urlparse(u)
        if not parsed.netloc:
            raise ValueError("URL inválida")
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        is_trusted = any(trusted in domain or domain.endswith('.' + trusted) for trusted in TRUSTED_EMBED_DOMAINS)
        if not is_trusted:
            raise ValueError("Domínio não permitido para embed")
        return u
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"URL de embed não permitida: {str(e)}")

def _validate_upload_file(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome")

    ext = Path(file.filename).suffix.lower()
    mime = file.content_type or ""

    if ext in ALLOWED_IMAGE_EXTENSIONS:
        if mime and mime not in ALLOWED_IMAGE_MIMES:
            raise HTTPException(status_code=400, detail="Tipo MIME inválido para imagem")
        max_size = MAX_IMAGE_SIZE
    elif ext in ALLOWED_VIDEO_EXTENSIONS:
        if mime and mime not in ALLOWED_VIDEO_MIMES:
            raise HTTPException(status_code=400, detail="Tipo MIME inválido para vídeo")
        max_size = MAX_VIDEO_SIZE
    else:
        raise HTTPException(status_code=400, detail=f"Extensão {ext} não permitida. Use: JPG, PNG, WEBP, GIF, MP4, MOV, WEBM")

    if ext in ALLOWED_IMAGE_EXTENSIONS and mime and mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(status_code=400, detail="Tipo de arquivo inválido (MIME mismatch)")
    if ext in ALLOWED_VIDEO_EXTENSIONS and mime and mime not in ALLOWED_VIDEO_MIMES:
        raise HTTPException(status_code=400, detail="Tipo de arquivo inválido (MIME mismatch)")

    if file.size and file.size > max_size:
        size_mb = max_size / (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Arquivo muito grande (máx {int(size_mb)}MB)")

    return ext, max_size

def _is_executable(ext: str) -> bool:
    return ext in {".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".scr", ".com", ".msi", ".dll", ".jar", ".py", ".js", ".php", ".pl", ".rb", ".asp", ".aspx", ".jsp"}

@asynccontextmanager
async def lifespan(app: FastAPI):
        init_db()
        yield

cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET")
    )

app = FastAPI(title="Intranet Diálogos API", lifespan=lifespan)

CORS_ORIGINS = os.getenv("CORS_ORIGINS")
if CORS_ORIGINS:
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
else:
    origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:3000",
        "https://intranet-dialogos.vercel.app",
        "https://intranet-dialogos-backend.onrender.com",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=r"https?://localhost(:\d+)?|https://.*\.vercel\.app",
)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

security = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            raise HTTPException(status_code=401, detail="Token ausente")
        payload = verify_token(credentials.credentials)
        if not payload:
            raise HTTPException(status_code=401, detail="Token inválido ou expirado")

        with get_db_context() as db:
            user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
            if not user_row:
                raise HTTPException(status_code=401, detail="Usuário não encontrado")
            return dict(user_row)

def get_current_user_from_token(token: str = Query(None), authorization: str = Header(None)):
    jwt_token = None
    if authorization and authorization.startswith('Bearer '):
        jwt_token = authorization[7:]
    elif token:
        jwt_token = token
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Token ausente")
    payload = verify_token(jwt_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    with get_db_context() as db:
        user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
        if not user_row:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        return dict(user_row)

def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            return None
        try:
            return get_current_user(credentials)
        except:
            return None

def require_level(min_level: int):
        def checker(user=Depends(get_current_user)):
            if user["access_level"] < min_level:
                raise HTTPException(status_code=403, detail="Acesso negado")
            return user
        return checker

def log_action(db, actor_key, target_key, action_type, details=""):
        db.execute(
            "INSERT INTO security_logs (id, actor_key, target_key, action_type, details, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                str(uuid.uuid4()),
                actor_key,
                target_key,
                action_type,
                details,
                datetime.datetime.utcnow().isoformat()
            )
        )

def require_diretor(user):
    if not user.get("is_diretor"):
        raise HTTPException(status_code=403, detail="Apenas diretores podem executar esta ação.")

def require_rh(user):
    if not user.get("is_rh") and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Apenas RH pode executar esta ação.")

def require_ouvidor(user):
    if not user.get("is_ouvidor") and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Apenas Ouvidores podem acessar esta funcionalidade.")

def log_audit(db, actor_id, action, target_user_id=None, detail=""):
    db.execute(
        "INSERT INTO audit_log (id, actor_id, action, target_user_id, detail, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), actor_id, action, target_user_id, detail, datetime.datetime.utcnow().isoformat())
    )


def extract_room_id(channel_value: str | None):
        if not channel_value:
            return None
        if channel_value.startswith("sala_"):
            return channel_value[5:]
        return None

def can_access_social_room(db, room_id: str, user):
        room = db.execute("SELECT * FROM social_rooms WHERE id=%s", (room_id,))
        room = db.fetchone()
        if not room:
            return False, None
        room_dict = dict(room)
        if not room_dict.get("is_private"):
            return True, room_dict
        if user["is_admin"] or user["is_admin_user"]:
            return True, room_dict
        member = db.execute(
            "SELECT 1 FROM social_room_members WHERE room_id=%s AND user_key=%s",
            (room_id, user["key"])
        )
        member = db.fetchone()
        return bool(member), room_dict

    # ── AUTH ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def login(body: LoginRequest, db=Depends(get_db)):
        user = db.execute("SELECT * FROM users WHERE key=%s", (body.key.lower(),))
        user = db.fetchone()
        if not user or not check_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        token = create_token({"sub": user["key"], "level": user["access_level"]})
        _notify(db, title="🔐 Login realizado",
                message=f"{user['name']} fez login no sistema",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                play_sound=False)
        return {
            "token": token,
            "must_change_password": not user["password_changed"],
            "user": {
                "key": user["key"], "name": user["name"], "initials": user["initials"],
                "role": user["role"], "dept": user["dept"], "level": user["level"],
                "color": user["color"], "access_level": user["access_level"],
                "is_admin": user["is_admin"], "is_admin_user": user["is_admin_user"],
                "is_rh": user["is_rh"], "is_ouvidor": user["is_ouvidor"],
                "is_diretor": user["is_diretor"], "is_leader": user["is_leader"],
                "is_orcoma": user["is_orcoma"],
                "nivel_dourado": bool(user.get("nivel_dourado")),
                "points": user["points"], "photo_url": user["photo_url"],
            }
        }

@app.get("/api/auth/me")
def auth_me(user=Depends(get_current_user)):
    return {
        "key": user["key"], "name": user["name"], "initials": user["initials"],
        "role": user["role"], "dept": user["dept"], "level": user["level"],
        "color": user["color"], "access_level": user["access_level"],
        "is_admin": user["is_admin"], "is_admin_user": user["is_admin_user"],
        "is_rh": user["is_rh"], "is_ouvidor": user["is_ouvidor"],
        "is_diretor": user["is_diretor"], "is_leader": user["is_leader"],
        "is_orcoma": user["is_orcoma"],
        "nivel_dourado": bool(user.get("nivel_dourado")),
        "points": user["points"], "photo_url": user["photo_url"],
        "password_changed": user["password_changed"],
    }

@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordRequest, user=Depends(get_current_user), db=Depends(get_db)):
        if not check_password(body.current_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Senha atual incorreta.")
        db.execute(
            "UPDATE users SET password_hash=%s, password_changed=1 WHERE key=%s",
            (hash_password(body.new_password), user["key"])
        )
        db.commit()
        log_action(db, user["key"], user["key"], "Troca Voluntária", "Usuário alterou a própria senha")
        return {"ok": True}

    # ── USERS ─────────────────────────────────────────────────────────────────────

@app.get("/api/users")
def list_users(user=Depends(get_current_user), db=Depends(get_db)):
        rows = db.execute("SELECT * FROM users ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d.pop("password_hash", None)
            # Se não for admin level>=2, esconde dados sensíveis
            if user["access_level"] < 2:
                d.pop("password_changed", None)
                d.pop("access_level", None)
            result.append(d)
        return result

@app.post("/api/users")
def create_user(body: CreateUserRequest, user=Depends(require_level(2)), db=Depends(get_db)):
        key = body.key.lower().strip()
        if db.execute("SELECT 1 FROM users WHERE key=%s", (key,)).fetchone():
            raise HTTPException(status_code=400, detail="Usuário já existe.")
        db.execute("""INSERT INTO users
            (key, name, initials, role, dept, level, color, access_level,
            is_admin, is_admin_user, is_rh, is_ouvidor, is_diretor, is_leader, nivel_dourado, points,
            password_hash, password_changed, photo_url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s)""",
            (key, body.name, body.initials, body.role, body.dept,
            body.level, body.color, body.access_level,
            1 if body.is_admin else 0, 1 if body.is_admin_user else 0,
            1 if body.is_rh else 0, 1 if body.is_ouvidor else 0,
            1 if body.is_diretor else 0, 1 if body.is_leader else 0,
            1 if body.nivel_dourado else 0,
            body.points, hash_password(body.password), "")
        )
        db.commit()
        log_action(db, user["key"], key, "Criação de Usuário", f"Criou usuário {body.name}")
        _notify(db, title="👤 Novo colaborador",
                message=f"{user['name']} criou o usuário {body.name} ({body.role})",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=key, play_sound=True)
        return {"ok": True}

@app.put("/api/users/{target_key}")
def update_user(target_key: str, body: UpdateUserRequest, user=Depends(get_current_user), db=Depends(get_db)):
        target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        # Self-edit OR admin >= level 2
        if user["key"] != target_key:
            if user["access_level"] < 2:
                raise HTTPException(status_code=403, detail="Sem permissão.")
            if user["access_level"] == 2 and target["access_level"] >= 2:
                raise HTTPException(status_code=403, detail="Você não pode editar admins.")
        db.execute("""UPDATE users SET name=%s, initials=%s, role=%s, dept=%s, level=%s,
            color=%s, access_level=%s, is_admin=%s, is_admin_user=%s, is_rh=%s, is_ouvidor=%s, is_diretor=%s, is_leader=%s, nivel_dourado=%s, points=%s
            WHERE key=%s""",
            (body.name, body.initials, body.role, body.dept, body.level,
            body.color, body.access_level,
            1 if body.is_admin else 0, 1 if body.is_admin_user else 0,
            1 if body.is_rh else 0, 1 if body.is_ouvidor else 0,
            1 if body.is_diretor else 0, 1 if body.is_leader else 0,
            1 if body.nivel_dourado else 0,
            body.points, target_key)
        )
        db.commit()
        return {"ok": True}

@app.post("/api/users/{target_key}/reset-password")
def reset_password(target_key: str, body: ResetPasswordRequest, user=Depends(require_level(2)), db=Depends(get_db)):
        target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        if user["access_level"] == 2 and target["access_level"] >= 2:
            raise HTTPException(status_code=403, detail="Regra de ouro: você não pode resetar admins do mesmo nível ou superior.")
        db.execute("UPDATE users SET password_hash=%s, password_changed=0 WHERE key=%s",
                (hash_password(body.new_password), target_key))
        db.commit()
        log_action(db, user["key"], target_key, "Reset de Senha",
                f"{user['name']} resetou a senha de {target['name']}")
        return {"ok": True}

@app.delete("/api/users/{target_key}")
def delete_user(target_key: str, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404)
    if user["access_level"] < 3 and target["access_level"] >= user["access_level"]:
        raise HTTPException(status_code=403, detail="Regra de ouro violada.")
    db.execute("DELETE FROM users WHERE key=%s", (target_key,))
    db.commit()
    log_action(db, user["key"], target_key, "Exclusão de Usuário", f"Removeu {target['name']}")
    return {"ok": True}

@app.post("/api/users/me/photo")
def upload_photo(file: UploadFile = File(...), user=Depends(get_current_user), db=Depends(get_db)):
    _check_upload_rate_limit(user["key"])
    ext, _ = _validate_upload_file(file)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato invalido. Use JPG, PNG ou WEBP.")

    try:
        unique_id = str(uuid.uuid4())
        result = cloudinary.uploader.upload(
            file.file,
            folder="dialogos/fotos",
            public_id=f"photo_{user['key']}_{unique_id}",
            overwrite=False
        )
        url = result["secure_url"]

        db.execute("UPDATE users SET photo_url=%s WHERE key=%s", (url, user["key"]))
        db.commit()
        _notify(db, title="📸 Foto atualizada",
                message=f"{user['name']} atualizou sua foto de perfil",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                play_sound=False)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/mural/{item_id}")
def delete_mural(item_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    item = db.execute("SELECT * FROM mural_items WHERE id=%s", (item_id,)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    if not (user["is_admin"] or user["is_admin_user"] or user["is_rh"]):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    db.execute("DELETE FROM mural_items WHERE id=%s", (item_id,))
    db.commit()
    return {"ok": True}

# ── SECURITY LOGS ─────────────────────────────────────────────────────────────

@app.get("/api/security-logs")
def get_logs(user=Depends(require_level(2)), db=Depends(get_db)):
    security = db.execute("SELECT * FROM security_logs ORDER BY created_at DESC LIMIT 200").fetchall()
    audit = db.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200").fetchall()
    combined = [dict(r) for r in security]
    for r in audit:
        d = dict(r)
        combined.append({
            "id": d["id"],
            "actor_key": d["actor_id"],
            "target_key": d.get("target_user_id"),
            "action_type": d["action"],
            "details": d.get("detail", ""),
            "created_at": d["created_at"],
        })
    combined.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return combined[:200]

# ── POSTS ─────────────────────────────────────────────────────────────────────

@app.get("/api/posts")
def get_posts(feed: str = "feed", limit: int = 20, offset: int = 0,
              user=Depends(get_current_user), db=Depends(get_db)):
    social_room_id = extract_room_id(feed)
    if social_room_id:
        allowed, _ = can_access_social_room(db, social_room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    rows = db.execute(
        "SELECT * FROM posts WHERE feed=%s ORDER BY pinned DESC, created_at DESC LIMIT %s OFFSET %s",
        (feed, limit, offset)
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM posts WHERE feed=%s", (feed,)).fetchone()[0]
    result = []
    for r in rows:
        d = dict(r)
        d["likes"] = json.loads(d.get("likes") or "[]")
        d["comments"] = json.loads(d.get("comments") or "[]")
        result.append(d)
    return {"posts": result, "total": total}

@app.post("/api/posts")
async def create_post(body: CreatePostRequest, user=Depends(get_current_user), db=Depends(get_db)):
    try:
        social_room_id = extract_room_id(body.feed)
        if social_room_id:
            allowed, _ = can_access_social_room(db, social_room_id, user)
            if not allowed:
                raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
        if body.feed == "novidades":
            can_post = (user["is_admin"] or user["is_admin_user"] or user["is_rh"] or
                        user["level"] in ["platina", "diamante"])
            if not can_post:
                raise HTTPException(status_code=403, detail="Sem permissão para publicar no Feed Novidades.")
        if body.feed == "colaboradores":
            pass  # All authenticated users can post
        elif body.feed == "internal":
            role = (user.get("role") or "").lower()
            can_post = (
                user.get("is_admin") or user.get("is_admin_user") or
                user.get("is_rh") or
                user.get("is_diretor") or user.get("is_leader") or
                role in ("diretora", "diretor", "líder", "lider", "admin", "rh")
            )
            if not can_post:
                raise HTTPException(status_code=403, detail="Sem permissão para publicar Comunicado Interno.")

        # Server-side validation for comunicado_tipo — never trust the client
        comunicado_tipo = body.comunicado_tipo
        if comunicado_tipo:
            role = (user.get("role") or "").lower()
            is_dir_role = role in ("diretora", "diretor")
            is_lider_role = role == "líder" or role == "lider"
            is_diretor = user.get("is_diretor") or False
            is_leader = user.get("is_leader") or False
            is_rh = user.get("is_rh") or False
            is_admin = user.get("is_admin") or False

            if comunicado_tipo == "direcao":
                if not is_diretor:
                    raise HTTPException(status_code=403, detail="Apenas a Direção pode publicar Comunicados da Direção.")
            elif comunicado_tipo == "diretoria":
                if not (is_dir_role or is_diretor or is_leader or is_admin):
                    raise HTTPException(status_code=403, detail="Sem permissão para Comunicado da Diretoria.")
            elif comunicado_tipo == "lideranca":
                if not (is_lider_role or is_leader or is_admin):
                    raise HTTPException(status_code=403, detail="Sem permissão para Comunicado da Liderança.")
            elif comunicado_tipo == "rh":
                if not (is_rh or is_admin):
                    raise HTTPException(status_code=403, detail="Sem permissão para Comunicado do RH.")
            elif comunicado_tipo == "admin":
                if not is_admin:
                    raise HTTPException(status_code=403, detail="Sem permissão para Comunicado Admin.")
            else:
                raise HTTPException(status_code=400, detail=f"Tipo de comunicado inválido: {comunicado_tipo}")

        safe_text = _sanitize_text(body.text or "")
        safe_embed = _validate_embed_url(body.embed_url) if body.embed_url else ""
        safe_image = body.image_url or ""
        safe_video = body.video_url or ""
        if safe_image and not safe_image.startswith("http"):
            safe_image = ""
        if safe_video and not safe_video.startswith("http"):
            safe_video = ""

        post_id = str(uuid.uuid4())
        db.execute("""INSERT INTO posts
    (id, feed, author_key, author_name, author_initials, author_color, author_photo_url,
    author_role, author_is_rh, author_is_admin,
    text, image_url, video_url, embed_url, access_level, comunicado_tipo, pinned, likes, comments, created_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
    (
        post_id,
        body.feed,
        user["key"],
        user["name"],
        user["initials"],
        user["color"],
        user.get("photo_url", ""),
        user.get("role", ""),
        1 if user.get("is_rh") else 0,
        1 if user.get("is_admin") else 0,
        safe_text,
        safe_image,
        safe_video,
        safe_embed,
        body.access_level,
        body.comunicado_tipo,
        0,
        '[]',
        '[]',
        datetime.datetime.utcnow().isoformat()
    )
)


        # ── Notification trigger ──
        is_comunicado = bool(body.comunicado_tipo)
        notif_title = "📢 Novo comunicado" if is_comunicado else "📋 Nova publicação"
        notif_msg = f"{user['name']} publicou: {(body.text or '')[:80]}"
        _notify(db, title=notif_title, message=notif_msg,
                ntype="comunicado" if is_comunicado else "post",
                audience=body.access_level if body.access_level not in ("all", "") else "all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=post_id, play_sound=False)
        # ── Mention triggers ──
        for mention_key in _extract_mentions(body.text):
            target = db.execute("SELECT key, name FROM users WHERE key=%s", (mention_key,)).fetchone()
            if target and target["key"] != user["key"]:
                _notify(db, title="👋 Você foi mencionado",
                        message=f"{user['name']} mencionou você em uma publicação",
                        ntype="mention", target_user_key=target["key"],
                        sender_key=user["key"], sender_name=user["name"],
                        reference_id=post_id, play_sound=True)
        db.commit()
        return {"ok": True, "id": post_id}
    except Exception as e:
        print(f"POST error: {e}")  # Backend log
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/posts/upload-image")
def upload_post_image(file: UploadFile = File(...), user=Depends(get_current_user)):
    _check_upload_rate_limit(user["key"])
    ext, _ = _validate_upload_file(file)

    resource_type = "video" if ext in ALLOWED_VIDEO_EXTENSIONS else "image"
    folder = "dialogos/posts"

    unique_name = f"{uuid.uuid4()}{ext}"

    result = cloudinary.uploader.upload(
        file.file,
        folder=folder,
        public_id=unique_name.replace(ext, ""),
        resource_type=resource_type
    )
    return {"url": result["secure_url"], "resource_type": resource_type}

@app.post("/api/posts/upload-video")
def upload_post_video(file: UploadFile = File(...), user=Depends(get_current_user)):
    _check_upload_rate_limit(user["key"])
    ext, _ = _validate_upload_file(file)
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato de vídeo não permitido. Use MP4, MOV ou WEBM")

    unique_name = f"{uuid.uuid4()}{ext}"
    result = cloudinary.uploader.upload(
        file.file,
        folder="dialogos/posts/videos",
        public_id=unique_name.replace(ext, ""),
        resource_type="video"
    )
    return {"url": result["secure_url"], "resource_type": "video"}

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
    is_new_like = user["key"] not in likes
    if user["key"] in likes:
        likes.remove(user["key"])
    else:
        likes.append(user["key"])
    db.execute("UPDATE posts SET likes=%s WHERE id=%s", (json.dumps(likes), post_id))
    # Notify post author on like
    post_dict = dict(post)
    if is_new_like and post_dict.get("author_key") and post_dict["author_key"] != user["key"]:
        _notify(db, title="👍 Nova curtida",
                message=f"{user['name']} curtiu sua publicação",
                ntype="post", target_user_key=post_dict["author_key"],
                sender_key=user["key"], sender_name=user["name"],
                reference_id=post_id, play_sound=True)
    db.commit()
    return {"likes": likes}

@app.post("/api/posts/{post_id}/comment")
def add_comment(post_id: str, body: CommentRequest, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    safe_text = _sanitize_text(body.text or "")
    if not safe_text.strip():
        raise HTTPException(status_code=400, detail="Comentário não pode ser vazio")
    comments = json.loads(post["comments"] or "[]")
    comments.append({
        "id": str(uuid.uuid4())[:8],
        "author_key": user["key"],
        "author_name": user["name"],
        "author_initials": user["initials"],
        "author_color": user.get("color", "av-gold"),
        "author_photo_url": user.get("photo_url", ""),
        "author_role": user.get("role", ""),
        "author_is_rh": user.get("is_rh", False),
        "text": safe_text,
        "created_at": datetime.datetime.utcnow().isoformat()
    })
    db.execute("UPDATE posts SET comments=%s WHERE id=%s", (json.dumps(comments), post_id))
    # Notify post author if different from commenter
    post_dict = dict(post)
    if post_dict.get("author_key") and post_dict["author_key"] != user["key"]:
        _notify(db, title="💬 Novo comentário",
                message=f"{user['name']} comentou: {(body.text or '')[:80]}",
                ntype="comment", target_user_key=post_dict["author_key"],
                sender_key=user["key"], sender_name=user["name"],
                reference_id=post_id, play_sound=True)
    # Mention triggers in comment
    for mention_key in _extract_mentions(body.text):
        target = db.execute("SELECT key FROM users WHERE key=%s", (mention_key,)).fetchone()
        if target and target["key"] != user["key"]:
            _notify(db, title="👋 Você foi mencionado",
                    message=f"{user['name']} mencionou você em um comentário",
                    ntype="mention", target_user_key=target["key"],
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=post_id, play_sound=True)
    db.commit()
    return {"comments": comments}

# ── POST VIEWS ─────────────────────────────────────────────────────────────────

@app.post("/api/posts/{post_id}/view")
def mark_post_viewed(post_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT id FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado")
    existing = db.execute(
        "SELECT 1 FROM post_views WHERE user_key=%s AND post_id=%s",
        (user["key"], post_id)
    ).fetchone()
    if not existing:
        db.execute(
            "INSERT INTO post_views (id, user_key, post_id, viewed_at) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), user["key"], post_id, datetime.datetime.utcnow().isoformat())
        )
        db.commit()
    return {"ok": True}

@app.get("/api/posts/{post_id}/view-count")
def get_post_view_count(post_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT id FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    row = db.execute("SELECT COUNT(*) as cnt FROM post_views WHERE post_id=%s", (post_id,)).fetchone()
    return {"count": row["cnt"] if row else 0}

@app.get("/api/posts/unviewed-counts")
def get_unviewed_counts(feed: str = "feed", user=Depends(get_current_user), db=Depends(get_db)):
    social_room_id = extract_room_id(feed)
    if social_room_id:
        allowed, _ = can_access_social_room(db, social_room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso.")
    rows = db.execute(
        "SELECT p.id FROM posts p WHERE p.feed=%s ORDER BY p.created_at DESC",
        (feed,)
    ).fetchall()
    total = len(rows)
    viewed_rows = db.execute(
        "SELECT pv.post_id FROM post_views pv WHERE pv.user_key=%s AND pv.post_id IN (SELECT id FROM posts WHERE feed=%s)",
        (user["key"], feed)
    ).fetchall()
    viewed_ids = {r["post_id"] for r in viewed_rows}
    unviewed_count = total - len(viewed_ids)
    unviewed_ids = [r["id"] for r in rows if r["id"] not in viewed_ids]
    return {
        "total": total,
        "unviewed_count": unviewed_count,
        "unviewed_ids": unviewed_ids[:50],
    }

# ── EVALUATIONS ────────────────────────────────────────────────────────────────

@app.get("/api/evaluations/{employee_id}")
def get_evaluations(employee_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    if user["key"] != employee_id and not (user.get("is_rh") or user.get("is_admin") or user.get("is_diretor") or user.get("is_leader")):
        raise HTTPException(status_code=403, detail="Sem permissão para ver avaliações.")
    rows = db.execute(
        "SELECT * FROM evaluations WHERE employee_id=%s ORDER BY created_at DESC",
        (employee_id,)
    ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/evaluations")
def create_evaluation(body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    evaluation_type = body.get("evaluation_type", "")
    employee_id = body.get("employee_id", "")
    positive = body.get("positive_feedback", "")[:10000]
    negative = body.get("negative_feedback", "")[:10000]
    extra = body.get("extra_notes", "")[:10000]
    stars = min(max(int(body.get("stars", 0)), 0), 5)
    score_delta = int(body.get("score_delta", 0))

    target = db.execute("SELECT * FROM users WHERE key=%s", (employee_id,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado.")

    if evaluation_type == "leader":
        if not user.get("is_leader") and not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Apenas líderes podem fazer Avaliação do Líder.")
        if user.get("is_leader") and not user.get("is_admin"):
            # Líder só pode avaliar subordinados (manager_key = user.key)
            if target.get("manager_key") != user["key"]:
                raise HTTPException(status_code=403, detail="Você só pode avaliar sua própria equipe.")
    elif evaluation_type == "rh":
        if not user.get("is_rh") and not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Apenas RH pode fazer Avaliação do RH.")
    elif evaluation_type == "diretor":
        if not user.get("is_diretor") and not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Apenas Diretores podem fazer Avaliação do Diretor.")
    else:
        raise HTTPException(status_code=400, detail="Tipo de avaliação inválido.")

    existing = db.execute(
        "SELECT id FROM evaluations WHERE employee_id=%s AND evaluation_type=%s",
        (employee_id, evaluation_type)
    ).fetchone()
    now = datetime.datetime.utcnow().isoformat()
    eid = str(uuid.uuid4())

    if existing:
        db.execute(
            """UPDATE evaluations SET positive_feedback=%s, negative_feedback=%s, extra_notes=%s,
               score_delta=%s, stars=%s, updated_at=%s WHERE id=%s""",
            (positive, negative, extra, score_delta, stars, now, existing["id"])
        )
        log_audit(db, user["key"], "evaluation_update", employee_id, f"Tipo: {evaluation_type}")
    else:
        db.execute(
            """INSERT INTO evaluations (id, employee_id, evaluator_id, evaluation_type,
               positive_feedback, negative_feedback, extra_notes, score_delta, stars, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (eid, employee_id, user["key"], evaluation_type, positive, negative, extra, score_delta, stars, now, now)
        )
        log_audit(db, user["key"], "evaluation_create", employee_id, f"Tipo: {evaluation_type}")

    if score_delta != 0:
        current_points = target["points"] or 0
        new_points = max(0, current_points + score_delta)
        db.execute("UPDATE users SET points=%s WHERE key=%s", (new_points, employee_id))

    _notify(db, title="📋 Avaliação recebida",
            message=f"Sua avaliação ({evaluation_type}) foi registrada por {user['name']}",
            ntype="system", target_user_key=employee_id,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=eid, play_sound=True)

    db.commit()
    return {"ok": True, "id": eid}

# ── COLLEAGUE FEEDBACK (LinkedIn-style) ───────────────────────────────────────

@app.get("/api/colleague-feedback/{target_key}")
def get_colleague_feedback(target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM colleague_feedback WHERE target_user_key=%s ORDER BY created_at DESC LIMIT 50",
        (target_key,)
    ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        entry["reactions"] = json.loads(entry.get("reactions") or "{}")
        can_delete = user["key"] == entry["author_key"] or user.get("is_admin")
        entry["can_delete"] = can_delete
        result.append(entry)
    return result

@app.post("/api/colleague-feedback")
def create_colleague_feedback(body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    target_key = body.get("target_user_key", "")
    text = body.get("text", "").strip()[:6000]
    if not text:
        raise HTTPException(status_code=400, detail="Feedback não pode ser vazio.")
    if user["key"] == target_key:
        raise HTTPException(status_code=400, detail="Você não pode avaliar a si mesmo.")

    target = db.execute("SELECT 1 FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    fid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO colleague_feedback (id, target_user_key, author_key, text, reactions, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (fid, target_key, user["key"], text, "{}", now)
    )
    log_audit(db, user["key"], "colleague_feedback_create", target_key, f"Feedback de {user['name']}")
    db.commit()
    return {"ok": True, "id": fid}

@app.put("/api/colleague-feedback/{feedback_id}")
def update_colleague_feedback(feedback_id: str, body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    fb = db.execute("SELECT * FROM colleague_feedback WHERE id=%s", (feedback_id,)).fetchone()
    if not fb:
        raise HTTPException(status_code=404)
    if fb["author_key"] != user["key"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Você não pode editar este feedback.")
    text = body.get("text", "").strip()[:6000]
    if not text:
        raise HTTPException(status_code=400, detail="Feedback não pode ser vazio.")
    now = datetime.datetime.utcnow().isoformat()
    db.execute("UPDATE colleague_feedback SET text=%s, updated_at=%s WHERE id=%s", (text, now, feedback_id))
    db.commit()
    return {"ok": True}

@app.delete("/api/colleague-feedback/{feedback_id}")
def delete_colleague_feedback(feedback_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    fb = db.execute("SELECT * FROM colleague_feedback WHERE id=%s", (feedback_id,)).fetchone()
    if not fb:
        raise HTTPException(status_code=404)
    if fb["author_key"] != user["key"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    db.execute("DELETE FROM colleague_feedback WHERE id=%s", (feedback_id,))
    db.commit()
    return {"ok": True}

@app.post("/api/colleague-feedback/{feedback_id}/react")
def react_to_feedback(feedback_id: str, body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    fb = db.execute("SELECT * FROM colleague_feedback WHERE id=%s", (feedback_id,)).fetchone()
    if not fb:
        raise HTTPException(status_code=404)
    reactions = json.loads(fb.get("reactions") or "{}")
    emoji = body.get("emoji", "")
    if emoji not in ("❤️", "👏", "🔥", "⭐"):
        raise HTTPException(status_code=400, detail="Reação inválida")
    user_key = user["key"]
    if user_key in reactions.get(emoji, []):
        reactions[emoji].remove(user_key)
        if not reactions[emoji]:
            del reactions[emoji]
    else:
        reactions.setdefault(emoji, []).append(user_key)
    db.execute("UPDATE colleague_feedback SET reactions=%s WHERE id=%s", (json.dumps(reactions), feedback_id))
    db.commit()
    return {"reactions": reactions}

# ── PRESENCE ───────────────────────────────────────────────────────────────────

@app.post("/api/presence/heartbeat")
def presence_heartbeat(user=Depends(get_current_user), db=Depends(get_db)):
    now = datetime.datetime.utcnow().isoformat()
    existing = db.execute("SELECT 1 FROM presence WHERE user_key=%s", (user["key"],)).fetchone()
    if existing:
        db.execute("UPDATE presence SET is_online=1, last_seen=%s, last_activity=%s WHERE user_key=%s",
                   (now, now, user["key"]))
    else:
        db.execute("INSERT INTO presence (user_key, is_online, last_seen, last_activity) VALUES (%s,1,%s,%s)",
                   (user["key"], now, now))
    db.commit()
    return {"ok": True}

@app.post("/api/presence/logout")
def presence_logout(user=Depends(get_current_user), db=Depends(get_db)):
    now = datetime.datetime.utcnow().isoformat()
    db.execute("UPDATE presence SET is_online=0, last_seen=%s WHERE user_key=%s", (now, user["key"]))
    db.commit()
    return {"ok": True}

@app.get("/api/presence")
def get_presence(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT user_key, is_online, last_seen, last_activity FROM presence").fetchall()
    return [dict(r) for r in rows]

# ── MURAL ITEMS ───────────────────────────────────────────────────────────────

@app.get("/api/mural")
def get_mural(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM mural_items ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/mural")
def create_mural(body: MuralItemRequest, user=Depends(get_current_user), db=Depends(get_db)):
    can_post = (user["is_admin"] or user["is_admin_user"] or user["is_rh"] or
                user["level"] in ["platina", "diamante"])
    if not can_post:
        raise HTTPException(status_code=403, detail="Sem permissão para publicar no mural.")
    item_id = str(uuid.uuid4())
    db.execute("""INSERT INTO mural_items (id, tag, title, subtitle, content, image_url, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (item_id, body.tag, body.title, body.subtitle, body.content,
        body.image_url or "", datetime.datetime.utcnow().isoformat())
    )
    _notify(db, title="🖼️ Novo mural",
            message=f"{user['name']} publicou no mural: {body.title or '(sem título)'}",
            ntype="post", audience="all",
            sender_key=user["key"], sender_name=user["name"],
            reference_id=item_id, play_sound=True)
    db.commit()
    return {"ok": True, "id": item_id}

@app.post("/api/mural/upload-image")
def upload_mural_image(
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    can_post = (
        user["is_admin"] or
        user["is_admin_user"] or
        user["is_rh"] or
        user["level"] in ["platina", "diamante"]
    )

    if not can_post:
        raise HTTPException(status_code=403)

    _check_upload_rate_limit(user["key"])
    ext, max_size = _validate_upload_file(file)

    unique_name = f"{uuid.uuid4()}{ext}"

    try:
        result = cloudinary.uploader.upload(
            file.file,
            folder="mural",
            public_id=unique_name.replace(ext, "")
        )

        return {
            "url": result["secure_url"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── FOLDERS & FILES ───────────────────────────────────────────────────────────

@app.get("/api/folders")
def get_folders(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM folders ORDER BY name").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/folders")
def create_folder(body: FolderRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if user["access_level"] < 2:
        has_nivel_dourado = user.get("nivel_dourado") if "nivel_dourado" in user else False
        if not has_nivel_dourado:
            raise HTTPException(status_code=403, detail="Apenas usuários com nível Dourado podem criar pastas.")
    fid = str(uuid.uuid4())
    db.execute("INSERT INTO folders (id, name, icon, level, drive_link, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
            (fid, body.name, body.icon, body.level, body.drive_link or "", user["key"]))
    log_audit(db, user["key"], "folder_create", None, f"Pasta: {body.name}")
    db.commit()
    return {"ok": True, "id": fid}

@app.put("/api/folders/{folder_id}")
def update_folder(folder_id: str, body: FolderRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    db.execute("UPDATE folders SET name=%s, icon=%s, level=%s, drive_link=%s WHERE id=%s",
            (body.name, body.icon, body.level, body.drive_link or "", folder_id))
    db.commit()
    return {"ok": True}

@app.delete("/api/folders/{folder_id}")
def delete_folder(folder_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    db.execute("DELETE FROM folders WHERE id=%s", (folder_id,))
    db.execute("DELETE FROM folder_files WHERE folder_id=%s", (folder_id,))
    db.commit()
    return {"ok": True}

@app.get("/api/folders/{folder_id}/files")
def get_folder_files(folder_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    folder = db.execute("SELECT * FROM folders WHERE id=%s", (folder_id,)).fetchone()
    if not folder:
        raise HTTPException(status_code=404)
    rows = db.execute("SELECT * FROM folder_files WHERE folder_id=%s ORDER BY created_at DESC", (folder_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/folders/{folder_id}/files")
def upload_folder_file(
    folder_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    if user["access_level"] < 2:
        raise HTTPException(status_code=403)
    _check_upload_rate_limit(user["key"])
    ext = Path(file.filename).suffix.lower()
    if _is_executable(ext):
        raise HTTPException(status_code=400, detail="Arquivos executáveis não são permitidos")
    
    try:
        unique_name = f"{uuid.uuid4()}{ext}"
        result = cloudinary.uploader.upload(
            file.file,
            folder="dialogos/folders",
            public_id=unique_name.replace(ext, ""),
            resource_type="auto"
        )
        url = result["secure_url"]
        
        file_id = str(uuid.uuid4())
        db.execute("""INSERT INTO folder_files (id, folder_id, name, url, size, mime_type, uploaded_by, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (file_id, folder_id, file.filename, url,
            file.size or 0, file.content_type or "",
            user["name"], datetime.datetime.utcnow().isoformat())
        )
        folder_name = db.execute("SELECT name FROM folders WHERE id=%s", (folder_id,)).fetchone()
        fname = folder_name["name"] if folder_name else "documentos"
        _notify(db, title="📎 Arquivo enviado",
                message=f"{user['name']} enviou {file.filename} para {fname}",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=file_id, play_sound=False)
        db.commit()
        return {"ok": True, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/folders/{folder_id}/files/{file_id}")
def delete_folder_file(folder_id: str, file_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    f = db.execute("SELECT * FROM folder_files WHERE id=%s AND folder_id=%s", (file_id, folder_id)).fetchone()
    if not f:
        raise HTTPException(status_code=404)
    db.execute("DELETE FROM folder_files WHERE id=%s", (file_id,))
    db.commit()
    return {"ok": True}

# ── CHAT (DM / SALAS) ─────────────────────────────────────────────────────────

@app.get("/api/chat/{room_id}")
def get_chat_messages(room_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    social_room_id = extract_room_id(room_id)
    if social_room_id:
        allowed, _ = can_access_social_room(db, social_room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    rows = db.execute(
        "SELECT * FROM chat_messages WHERE room_id=%s ORDER BY created_at ASC LIMIT 500",
        (room_id,)
    ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/chat")
def send_chat_message(body: ChatMessageRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Mensagem vazia.")
    social_room_id = extract_room_id(body.room_id)
    if social_room_id:
        allowed, _ = can_access_social_room(db, social_room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    mid = str(uuid.uuid4())
    db.execute("""INSERT INTO chat_messages
        (id, room_id, sender_key, sender_name, sender_photo, sender_initials, sender_color, text, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            mid,
            body.room_id,
            user["key"],
            user["name"],
            user.get("photo_url", ""),
            user.get("initials", ""),
            user.get("color", "av-gold"),
            body.text.strip(),
            datetime.datetime.utcnow().isoformat()
        )
    )
    # Mention triggers in chat
    for mention_key in _extract_mentions(body.text):
        target = db.execute("SELECT key FROM users WHERE key=%s", (mention_key,)).fetchone()
        if target and target["key"] != user["key"]:
            _notify(db, title="💬 Você foi mencionado no chat",
                    message=f"{user['name']}: {(body.text or '')[:80]}",
                    ntype="mention", target_user_key=target["key"],
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=mid, play_sound=True)
    # Notify social room members about new message (non-mention)
    social_room_id = extract_room_id(body.room_id)
    if social_room_id:
        members = db.execute(
            "SELECT user_key FROM social_room_members WHERE room_id=%s AND user_key!=%s",
            (social_room_id, user["key"])
        ).fetchall()
        for m in members:
            _notify(db, title="💬 Nova mensagem na sala",
                    message=f"{user['name']}: {(body.text or '')[:80]}",
                    ntype="comment", target_user_key=m["user_key"],
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=mid, play_sound=False)
    else:
        # DM notification — notify the other participant(s)
        other_senders = db.execute(
            "SELECT DISTINCT sender_key FROM chat_messages WHERE room_id=%s AND sender_key!=%s",
            (body.room_id, user["key"])
        ).fetchall()
        if not other_senders:
            # First message in DM — infer receiver from room_id
            parts = body.room_id.split('_')
            if len(parts) == 2:
                receiver_key = parts[1] if parts[0] == user['key'] else parts[0]
                other_user = db.execute("SELECT key FROM users WHERE key=%s", (receiver_key,)).fetchone()
                if other_user:
                    other_senders = [{"sender_key": receiver_key}]
        for o in other_senders:
            _notify(db, title="💬 Nova mensagem",
                    message=f"{user['name']}: {(body.text or '')[:80]}",
                    ntype="chat", target_user_key=o["sender_key"],
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=mid, play_sound=True)
    db.commit()
    return {"ok": True, "id": mid}

@app.get("/api/chat/recent")
def get_recent_chats(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT room_id, MAX(created_at) as last_at, COUNT(*) as msg_count
        FROM chat_messages
        WHERE room_id NOT LIKE 'sala_%%'
          AND (room_id LIKE %s OR room_id LIKE %s)
        GROUP BY room_id ORDER BY last_at DESC LIMIT 20
    """, (f"{user['key']}_%", f"%_{user['key']}")).fetchall()
    result = []
    for r in rows:
        parts = r["room_id"].split("_")
        other_key = parts[1] if parts[0] == user["key"] else parts[0]
        ou = db.execute(
            "SELECT key,name,initials,photo_url,color,role FROM users WHERE key=%s",
            (other_key,)
        ).fetchone()
        ou_dict = dict(ou) if ou else None
        last = db.execute(
            "SELECT text,sender_key,created_at FROM chat_messages WHERE room_id=%s ORDER BY created_at DESC LIMIT 1",
            (r["room_id"],)
        ).fetchone()
        last_dict = dict(last) if last else None
        result.append({
            "room_id": r["room_id"],
            "other_key": other_key,
            "other_name": ou_dict["name"] if ou_dict else other_key,
            "other_initials": ou_dict["initials"] if ou_dict else "?",
            "other_photo": ou_dict.get("photo_url", "") if ou_dict else "",
            "other_color": ou_dict.get("color", "#C9A84C") if ou_dict else "#C9A84C",
            "last_message": (last_dict["text"] or "")[:80] if last_dict else "",
            "last_sender_key": last_dict["sender_key"] if last_dict else "",
            "last_at": r["last_at"],
            "message_count": r["msg_count"],
        })
    return result

# ── SOCIAL / COMUNIDADE ───────────────────────────────────────────────────────

@app.get("/api/social-rooms")
def list_social_rooms(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM social_rooms ORDER BY created_at ASC").fetchall()
    result = []
    for r in rows:
        room = dict(r)
        allowed, _ = can_access_social_room(db, room["id"], user)
        if not allowed:
            continue
        room["posts_feed"] = f"sala_{room['id']}"
        room["chat_room_id"] = f"sala_{room['id']}"
        room["files_count"] = db.execute(
            "SELECT COUNT(*) FROM social_room_files WHERE room_id=%s",
            (room["id"],)
        ).fetchone()["count"]
        room["members_count"] = db.execute(
            "SELECT COUNT(*) FROM social_room_members WHERE room_id=%s",
            (room["id"],)
        ).fetchone()["count"]
        room["is_member"] = bool(db.execute(
            "SELECT 1 FROM social_room_members WHERE room_id=%s AND user_key=%s",
            (room["id"], user["key"])
        ).fetchone())
        result.append(room)
    return result

@app.post("/api/social-rooms")
def create_social_room(body: SocialRoomRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Nome da sala é obrigatório.")
    room_id = str(uuid.uuid4())
    db.execute("""INSERT INTO social_rooms (id, name, description, created_by, created_at, is_private)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (
            room_id,
            body.name.strip(),
            (body.description or "").strip(),
            user["key"],
            datetime.datetime.utcnow().isoformat(),
            1 if body.is_private else 0,
        )
    )
    db.execute("""INSERT INTO social_room_members (id, room_id, user_key, added_by, created_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING""",
        (str(uuid.uuid4()), room_id, user["key"], user["key"], datetime.datetime.utcnow().isoformat())
    )
    for member_key in (body.member_keys or []):
        k = (member_key or "").strip().lower()
        if not k or k == user["key"]:
            continue
        exists = db.execute("SELECT 1 FROM users WHERE key=%s", (k,)).fetchone()
        if not exists:
            continue
        db.execute("""INSERT INTO social_room_members (id, room_id, user_key, added_by, created_at)
    VALUES (%s,%s,%s,%s,%s)
    ON CONFLICT DO NOTHING""",
    (str(uuid.uuid4()), room_id, k, user["key"], datetime.datetime.utcnow().isoformat())
)
    db.commit()
    return {"ok": True, "id": room_id}

@app.delete("/api/social-rooms/{room_id}")
def delete_social_room(room_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    room = db.execute("SELECT * FROM social_rooms WHERE id=%s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")
    if room["created_by"] != user["key"] and not (user["is_admin"] or user["is_admin_user"]):
        raise HTTPException(status_code=403, detail="Sem permissão para remover esta sala.")

    room_feed = f"sala_{room_id}"
    room_chat = f"sala_{room_id}"

    db.execute("DELETE FROM social_rooms WHERE id=%s", (room_id,))
    db.execute("DELETE FROM social_room_files WHERE room_id=%s", (room_id,))
    db.execute("DELETE FROM social_room_members WHERE room_id=%s", (room_id,))
    db.execute("DELETE FROM posts WHERE feed=%s", (room_feed,))
    db.execute("DELETE FROM chat_messages WHERE room_id=%s", (room_chat,))
    db.commit()
    return {"ok": True}

@app.get("/api/social-rooms/{room_id}/members")
def list_social_room_members(room_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    allowed, room = can_access_social_room(db, room_id, user)
    if not allowed:
        raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    rows = db.execute("""
        SELECT m.user_key, m.added_by, m.created_at, u.name, u.initials, u.role, u.photo_url
        FROM social_room_members m
        JOIN users u ON u.key = m.user_key
        WHERE m.room_id=%s
        ORDER BY u.name
    """, (room_id,)).fetchall()
    return {"room": dict(room), "members": [dict(r) for r in rows]}

@app.post("/api/social-rooms/{room_id}/members/{target_key}")
def add_social_room_member(room_id: str, target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    room = db.execute("SELECT * FROM social_rooms WHERE id=%s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")
    if room["created_by"] != user["key"] and not (user["is_admin"] or user["is_admin_user"]):
        raise HTTPException(status_code=403, detail="Sem permissão para adicionar membros.")
    k = target_key.strip().lower()
    exists = db.execute("SELECT 1 FROM users WHERE key=%s", (k,)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    db.execute(
    """
    INSERT INTO social_room_members
    (id, room_id, user_key, added_by, created_at)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING
    """,
    (
        str(uuid.uuid4()),
        room_id,
        k,
        user["key"],
        datetime.datetime.utcnow().isoformat()
    )
    )
    _notify(db, title="👋 Você foi adicionado a uma sala",
            message=f"{user['name']} adicionou você à sala {room['name']}",
            ntype="system", target_user_key=k,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=room_id, play_sound=True)
    db.commit()
    return {"ok": True}


@app.delete("/api/social-rooms/{room_id}/members/{target_key}")
def remove_social_room_member(room_id: str, target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    room = db.execute("SELECT * FROM social_rooms WHERE id=%s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")
    if room["created_by"] != user["key"] and not (user["is_admin"] or user["is_admin_user"]):
        raise HTTPException(status_code=403, detail="Sem permissão para remover membros.")
    k = target_key.strip().lower()
    if k == room["created_by"]:
        raise HTTPException(status_code=400, detail="O criador da sala não pode ser removido.")
    db.execute("DELETE FROM social_room_members WHERE room_id=%s AND user_key=%s", (room_id, k))
    db.commit()
    return {"ok": True}

@app.get("/api/social-rooms/{room_id}/files")
def list_social_room_files(room_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    allowed, _ = can_access_social_room(db, room_id, user)
    if not allowed:
        raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    rows = db.execute(
        "SELECT * FROM social_room_files WHERE room_id=%s ORDER BY created_at DESC",
        (room_id,)
    ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/social-rooms/{room_id}/files")
def upload_social_room_file(
    room_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    allowed, _ = can_access_social_room(db, room_id, user)
    if not allowed:
        raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    _check_upload_rate_limit(user["key"])
    ext = Path(file.filename).suffix.lower()
    if _is_executable(ext):
        raise HTTPException(status_code=400, detail="Arquivos executáveis não são permitidos")

    try:
        unique_name = f"{uuid.uuid4()}{ext}"
        result = cloudinary.uploader.upload(
            file.file,
            folder=f"dialogos/social_rooms/{room_id}",
            public_id=unique_name.replace(ext, ""),
            resource_type="auto"
        )
        url = result["secure_url"]

        file_id = str(uuid.uuid4())
        db.execute("""INSERT INTO social_room_files (id, room_id, name, url, size, mime_type, uploaded_by, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                file_id,
                room_id,
                file.filename,
                url,
                file.size or 0,
                file.content_type or "",
                user["name"],
                datetime.datetime.utcnow().isoformat()
            )
        )
        db.commit()
        return {"ok": True, "id": file_id, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/social-rooms/{room_id}/files/{file_id}")
def delete_social_room_file(room_id: str, file_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    allowed, room = can_access_social_room(db, room_id, user)
    if not allowed:
        raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")

    entry = db.execute(
        "SELECT * FROM social_room_files WHERE id=%s AND room_id=%s",
        (file_id, room_id)
    ).fetchone()
    if not entry:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    if room["created_by"] != user["key"] and not (user["is_admin"] or user["is_admin_user"]):
        raise HTTPException(status_code=403, detail="Sem permissão para remover arquivos desta sala.")

    db.execute("DELETE FROM social_room_files WHERE id=%s", (file_id,))
    db.commit()
    return {"ok": True}

# ── OUVIDORIA ─────────────────────────────────────────────────────────────────

@app.get("/api/ouvidoria")
def get_ouvidoria(user=Depends(get_current_user), db=Depends(get_db)):
    is_ouvidor = user.get("is_ouvidor") or (user.get("role") or "").lower() == "ouvidor"
    if not is_ouvidor and not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Acesso restrito a Ouvidores.")
    rows = db.execute("SELECT * FROM ouvidoria ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/ouvidoria")
def create_ouvidoria(body: OuvidoriaRequest, user=Depends(get_current_user), db=Depends(get_db)):
    oid = str(uuid.uuid4())
    db.execute("""INSERT INTO ouvidoria (id, author_key, author_name, category, text, status, created_at)
        VALUES (%s,%s,%s,%s,%s,'aberta',%s)""",
        (oid, user["key"], user["name"], body.category, body.text,
        datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": oid}

@app.put("/api/ouvidoria/{oid}/status")
def update_ouvidoria_status(oid: str, body: OuvidoriaStatusRequest, user=Depends(get_current_user), db=Depends(get_db)):
    is_ouvidor = user.get("is_ouvidor") or (user.get("role") or "").lower() == "ouvidor"
    if not is_ouvidor and not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Apenas Ouvidores podem alterar status.")
    db.execute("UPDATE ouvidoria SET status=%s WHERE id=%s", (body.status, oid))
    log_audit(db, user["key"], "ouvidoria_status", None, f"Status alterado para {body.status}")
    db.commit()
    return {"ok": True}

@app.post("/api/ouvidoria/{oid}/respond")
def respond_ouvidoria(oid: str, body: OuvidoriaResponseRequest, user=Depends(get_current_user), db=Depends(get_db)):
    is_ouvidor = user.get("is_ouvidor") or (user.get("role") or "").lower() == "ouvidor"
    if not is_ouvidor and not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Apenas Ouvidores podem responder.")
    ouid = db.execute("SELECT responses FROM ouvidoria WHERE id=%s", (oid,)).fetchone()
    if not ouid:
        raise HTTPException(status_code=404, detail="Ouvidoria não encontrada")
    responses = json.loads(ouid[0] or "[]")
    responses.append({
        "responder_key": user["key"],
        "responder_name": user["name"],
        "text": body.text,
        "created_at": datetime.datetime.utcnow().isoformat()
    })
    db.execute("UPDATE ouvidoria SET responses=%s WHERE id=%s", (json.dumps(responses), oid))
    # Notify original author
    ouid_full = db.execute("SELECT author_key FROM ouvidoria WHERE id=%s", (oid,)).fetchone()
    if ouid_full and ouid_full["author_key"] != user["key"]:
        _notify(db, title="📬 Ouvidoria respondida",
                message=f"{user['name']} respondeu sua manifestação",
                ntype="system", target_user_key=ouid_full["author_key"],
                sender_key=user["key"], sender_name=user["name"],
                reference_id=oid, play_sound=True)
    db.commit()
    return {"ok": True}

# ── RANKING ───────────────────────────────────────────────────────────────────

@app.get("/api/ranking")
def get_ranking(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT key, name, initials, color, level, role, dept, points, photo_url FROM users ORDER BY points DESC").fetchall()
    all_users = [dict(r) for r in rows]
    total = len(all_users)
    my_position = next((i+1 for i, u in enumerate(all_users) if u["key"] == user["key"]), None)
    top10 = []
    for i, u in enumerate(all_users[:10], 1):
        entry = dict(u)
        entry["position"] = i
        top10.append(entry)
    return {
        "top10": top10,
        "myRank": {"position": my_position} if my_position else None,
        "totalUsers": total
    }

@app.put("/api/users/{target_key}/points")
def update_points(target_key: str, body: PointsRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT name, points FROM users WHERE key=%s", (target_key,)).fetchone()
    old_points = target["points"] or 0
    new_points = body.points
    db.execute("UPDATE users SET points=%s WHERE key=%s", (new_points, target_key))
    log_audit(db, user["key"], "points_update", target_key,
              f"Pontos alterados: {old_points} → {new_points} (por {user['name']})")
    _notify(db, title="📊 Pontos atualizados",
            message=f"Seus pontos foram atualizados de {old_points} para {new_points} por {user['name']}",
            ntype="xp", target_user_key=target_key,
            sender_key=user["key"], sender_name=user["name"],
            play_sound=True)
    db.commit()
    return {"ok": True}

# ── ORGANOGRAM ────────────────────────────────────────────────────────────────

@app.get("/api/organogram")
def get_organogram(db=Depends(get_db)):
    rows = db.execute("""SELECT o.*, u.name, u.color FROM organogram o
        LEFT JOIN users u ON o.user_key = u.key ORDER BY o.position_order ASC""").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/organogram")
def save_organogram(entries: list[OrgEntry], user=Depends(require_level(2)), db=Depends(get_db)):
    db.execute("DELETE FROM organogram")
    for entry in entries:
        org_id = str(uuid.uuid4())
        db.execute("""INSERT INTO organogram (id, user_key, parent_key, position_order, org_tier)
            VALUES (%s,%s,%s,%s,%s)""",
            (org_id, entry.user_key, entry.parent_key or "", entry.position_order, entry.org_tier)
        )
    db.commit()
    return {"ok": True}

# ── MOOD ──────────────────────────────────────────────────────────────────────

MOOD_VALUES = {1: "muito_triste", 2: "triste", 3: "neutro", 4: "feliz", 5: "muito_feliz"}
MOOD_EMOJIS = {1: "\U0001F61E", 2: "\U0001F641", 3: "\U0001F610", 4: "\U0001F642", 5: "\U0001F604"}

_mood_rate = {}

def _check_mood_rate_limit(user_key: str):
    hoje = datetime.date.today().isoformat()
    key = f"mood:{user_key}:{hoje}"
    count = _mood_rate.get(key, 0)
    if count >= 5:
        raise HTTPException(status_code=429, detail="Limite diário de 5 registros de humor atingido.")
    _mood_rate[key] = count + 1

@app.post("/api/mood")
def save_mood(body: MoodRequest, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    if body.valor_humor is not None:
        if body.valor_humor not in MOOD_VALUES:
            raise HTTPException(status_code=422, detail="valor_humor deve ser inteiro entre 1 e 5.")
        mood_key = MOOD_VALUES[body.valor_humor]
    elif body.mood:
        mood_key = body.mood
    else:
        raise HTTPException(status_code=422, detail="Informe valor_humor (1-5) ou mood.")

    _check_mood_rate_limit(user["key"])

    intensity = body.intensity if body.intensity else None

    db.execute("""INSERT INTO mood_history (id, user_key, mood, intensity, reason, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), user["key"], mood_key, intensity, body.reason or "",
        datetime.datetime.utcnow().isoformat())
    )

    _log_atividade(db, "humor", user["key"],
                   f"{user['name']} respondeu o Termômetro do Humor")

    db.commit()

    ip = request.client.host if request.client else "desconhecido"
    log_action(db, user["key"], user["key"], "Registro de Humor",
               f"valor_humor={body.valor_humor or mood_key} IP={ip}")

    return {"ok": True, "valor_humor": body.valor_humor or None}

@app.get("/api/mood/history")
def get_mood_history(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM mood_history WHERE user_key=%s ORDER BY created_at DESC LIMIT 100",
                    (user["key"],)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/mood/reset")
def reset_mood(user=Depends(get_current_user), db=Depends(get_db)):
    db.execute("DELETE FROM mood_history WHERE user_key=%s", (user["key"],))
    db.commit()
    return {"ok": True}


# ── RELATÓRIO DE HUMOR ────────────────────────────────────────────────────────

def _pode_ver_relatorio(user: dict, paciente_key: str) -> bool:
    if user["key"] == paciente_key:
        return True
    if user.get("is_admin") or user.get("is_admin_user"):
        return True
    return False

@app.get("/api/relatorio/humor/{paciente_key}")
def get_relatorio_humor(paciente_key: str, data_inicio: str = None, data_fim: str = None,
                        user=Depends(get_current_user), db=Depends(get_db)):
    if not _pode_ver_relatorio(user, paciente_key):
        raise HTTPException(status_code=403, detail="Sem permissão para ver relatório deste paciente.")

    paciente = db.execute("SELECT key, name, photo_url FROM users WHERE key=%s", (paciente_key,)).fetchone()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")

    conditions = ["user_key=%s"]
    params = [paciente_key]
    if data_inicio:
        conditions.append("created_at >= %s")
        params.append(data_inicio)
    if data_fim:
        conditions.append("created_at <= %s")
        params.append(data_fim + "T23:59:59")

    where = " AND ".join(conditions)
    rows = db.execute(
        f"SELECT * FROM mood_history WHERE {where} ORDER BY created_at ASC",
        params
    ).fetchall()

    registros = [dict(r) for r in rows]

    translated = []
    for r in registros:
        val = None
        for v, k in MOOD_VALUES.items():
            if r["mood"] == k:
                val = v
                break
        translated.append({
            "id": r["id"],
            "data": r["created_at"][:10] if r["created_at"] else "",
            "hora": r["created_at"][11:16] if r["created_at"] else "",
            "valor_humor": val,
            "emoji": MOOD_EMOJIS.get(val, "?"),
            "label": MOOD_VALUES.get(val, r["mood"]),
            "intensity": r.get("intensity"),
            "reason": r.get("reason", ""),
        })

    valores = [t["valor_humor"] for t in translated if t["valor_humor"]]
    media = sum(valores) / len(valores) if valores else 0
    melhor = max(valores) if valores else None
    pior = min(valores) if valores else None

    melhor_dia = None
    pior_dia = None
    if melhor is not None:
        melhores = [t for t in translated if t["valor_humor"] == melhor]
        melhor_dia = melhores[0]["data"] if melhores else None
    if pior is not None:
        piores = [t for t in translated if t["valor_humor"] == pior]
        pior_dia = piores[0]["data"] if piores else None

    return {
        "paciente": dict(paciente),
        "periodo": {"inicio": data_inicio, "fim": data_fim},
        "total": len(translated),
        "media": round(media, 2),
        "melhor_valor": melhor,
        "melhor_dia": melhor_dia,
        "pior_valor": pior,
        "pior_dia": pior_dia,
        "registros": translated,
    }


@app.get("/api/relatorio/humor/{paciente_key}/pdf")
def download_relatorio_humor_pdf(paciente_key: str, data_inicio: str = None, data_fim: str = None,
                                  user=Depends(get_current_user_from_token), db=Depends(get_db)):
    if not _pode_ver_relatorio(user, paciente_key):
        raise HTTPException(status_code=403, detail="Sem permissão.")

    paciente = db.execute("SELECT key, name FROM users WHERE key=%s", (paciente_key,)).fetchone()
    if not paciente:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")

    conditions = ["user_key=%s"]
    params = [paciente_key]
    if data_inicio:
        conditions.append("created_at >= %s")
        params.append(data_inicio)
    if data_fim:
        conditions.append("created_at <= %s")
        params.append(data_fim + "T23:59:59")

    where = " AND ".join(conditions)
    rows = db.execute(
        f"SELECT * FROM mood_history WHERE {where} ORDER BY created_at ASC",
        params
    ).fetchall()

    registros = [dict(r) for r in rows]

    from fpdf import FPDF
    import os
    from io import BytesIO

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Fonte com suporte a emojis
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "NotoEmoji-Regular.ttf")
    pdf.add_font("NotoEmoji", "", font_path)

    # Logo
    logo_path = os.path.join("..", "frontend", "public", "logo-clinica-fivecon.ico")
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=10, w=12)

    pdf.set_font("NotoEmoji", size=16)
    pdf.cell(0, 10, "Clinica Dialogos - Relatorio de Humor", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("NotoEmoji", size=11)
    pdf.cell(0, 8, f"Paciente: {paciente['name']}", new_x="LMARGIN", new_y="NEXT")
    periodo = f"{data_inicio or 'inicio'} a {data_fim or 'hoje'}"
    pdf.cell(0, 8, f"Periodo: {periodo}", new_x="LMARGIN", new_y="NEXT")

    valores_pdf = []
    translated_pdf = []
    for r in registros:
        val = None
        for v, k in MOOD_VALUES.items():
            if r["mood"] == k:
                val = v
                break
        translated_pdf.append({
            "data": r["created_at"][:10] if r["created_at"] else "",
            "hora": r["created_at"][11:16] if r["created_at"] else "",
            "valor": val,
            "label": MOOD_VALUES.get(val, r["mood"]),
        })
        if val:
            valores_pdf.append(val)

    media_val = sum(valores_pdf) / len(valores_pdf) if valores_pdf else 0
    melhor_val = max(valores_pdf) if valores_pdf else None
    pior_val = min(valores_pdf) if valores_pdf else None

    pdf.ln(10)
    pdf.set_font("NotoEmoji", size=12)
    pdf.cell(0, 8, "Resumo", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NotoEmoji", size=11)
    pdf.cell(0, 7, f"Total de registros: {len(translated_pdf)}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Humor medio: {media_val:.1f} / 5", new_x="LMARGIN", new_y="NEXT")
    if melhor_val is not None:
        pdf.cell(0, 7, f"Melhor humor: {melhor_val} - {MOOD_EMOJIS.get(melhor_val, '')}", new_x="LMARGIN", new_y="NEXT")
    if pior_val is not None:
        pdf.cell(0, 7, f"Pior humor: {pior_val} - {MOOD_EMOJIS.get(pior_val, '')}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("NotoEmoji", size=12)
    pdf.cell(0, 8, "Registros", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("NotoEmoji", size=9)

    # Table header
    col_w = [30, 20, 40, 60]
    headers_pdf = ["Data", "Hora", "Humor", "Valor"]
    for i, h in enumerate(headers_pdf):
        pdf.cell(col_w[i], 7, h, border=1)
    pdf.ln()

    for t in translated_pdf:
        pdf.cell(col_w[0], 6, t["data"], border=1)
        pdf.cell(col_w[1], 6, t["hora"], border=1)
        pdf.cell(col_w[2], 6, t["label"], border=1)
        valor_str = str(t["valor"]) if t["valor"] else "-"
        pdf.cell(col_w[3], 6, valor_str, border=1)
        pdf.ln()

    pdf.set_font("NotoEmoji", size=10)
    pdf.cell(0, 10, f"Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}", new_x="LMARGIN", new_y="NEXT", align="C")

    nome_arquivo = f"relatorio_humor_{paciente['name'].replace(' ', '_')}_{datetime.date.today().isoformat()}.pdf"
    buf = BytesIO()
    pdf.output(buf)
    pdf_bytes = buf.getvalue()

    from starlette.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'}
    )

# ── ATIVIDADES DIÁLOGOS ───────────────────────────────────────────────────────

def _log_atividade(db, tipo: str, autor_key: str, descricao: str, target_key: str = None, target_nome: str = None):
    db.execute(
        """INSERT INTO atividades_dialogos (id, tipo, autor_key, target_key, target_nome, descricao, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), tipo, autor_key, target_key, target_nome,
         descricao, datetime.datetime.utcnow().isoformat())
    )


@app.get("/api/atividades")
def listar_atividades(limit: int = 50, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute(
        """SELECT a.*, u.name AS autor_nome, u.initials AS autor_initials,
                  u.color AS autor_color, u.photo_url AS autor_photo
           FROM atividades_dialogos a
           LEFT JOIN users u ON u.key = a.autor_key
           ORDER BY a.created_at DESC LIMIT %s""",
        (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


class ParabensRequest(BaseModel):
    target_key: str
    mensagem: str


@app.post("/api/atividades/parabens")
def criar_parabens(body: ParabensRequest, user=Depends(get_current_user), db=Depends(get_db)):
    target_key = body.target_key.strip().lower() if body.target_key else ""
    mensagem = _sanitize_text(body.mensagem or "")[:500]

    if not target_key and not mensagem:
        raise HTTPException(status_code=422, detail="Informe o destinatário ou mensagem.")

    target_nome = None
    if target_key and target_key != "@todos":
        t = db.execute("SELECT name FROM users WHERE key=%s", (target_key,)).fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        target_nome = t["name"]

    alvo = target_nome or "@todos" if target_key == "@todos" else (target_nome or "equipe")
    descricao = f"{user['name']} parabenizou {alvo}"
    if mensagem:
        descricao += f" — {mensagem}"

    _log_atividade(db, "parabens", user["key"], descricao, target_key or "@todos", target_nome or "@todos")
    db.commit()
    return {"ok": True}


# ── PRICE DOCTORS (Tabela de Preços) ──────────────────────────────────────────

@app.get("/api/price-doctors")
def get_price_doctors(folder_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM price_doctors WHERE folder_id=%s ORDER BY position_order ASC",
                    (folder_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/price-doctors")
def create_price_doctor(body: PriceDoctorRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    doctor_id = str(uuid.uuid4())
    db.execute("""INSERT INTO price_doctors (id, folder_id, name, specialty, crm, rqe, position_order, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (doctor_id, body.folder_id, body.name, body.specialty or "", body.crm or "",
        body.rqe or "", body.position_order, datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": doctor_id}

@app.put("/api/price-doctors/{doctor_id}")
def update_price_doctor(doctor_id: str, body: PriceDoctorRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    db.execute("""UPDATE price_doctors SET name=%s, specialty=%s, crm=%s, rqe=%s, position_order=%s WHERE id=%s""",
        (body.name, body.specialty or "", body.crm or "", body.rqe or "", body.position_order, doctor_id)
    )
    db.commit()
    return {"ok": True}

@app.delete("/api/price-doctors/{doctor_id}")
def delete_price_doctor(doctor_id: str, user=Depends(require_level(1)), db=Depends(get_db)):
    db.execute("DELETE FROM price_procedures WHERE doctor_id=%s", (doctor_id,))
    db.execute("DELETE FROM price_doctors WHERE id=%s", (doctor_id,))
    db.commit()
    return {"ok": True}

@app.get("/api/price-procedures/{doctor_id}")
def get_price_procedures(doctor_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM price_procedures WHERE doctor_id=%s ORDER BY position_order ASC",
                    (doctor_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/price-procedures")
def create_price_procedure(body: PriceProcedureRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    proc_id = str(uuid.uuid4())
    db.execute("""INSERT INTO price_procedures
        (id, doctor_id, name, value_cash, value_card_pix, value_bradesco, value_brv, value_prefeitura, position_order, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (proc_id, body.doctor_id, body.name, body.value_cash or 0, body.value_card_pix or 0,
        body.value_bradesco or 0, body.value_brv or 0, body.value_prefeitura or 0,
        body.position_order, datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": proc_id}

@app.put("/api/price-procedures/{proc_id}")
def update_price_procedure(proc_id: str, body: PriceProcedureRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    db.execute("""UPDATE price_procedures SET name=%s, value_cash=%s, value_card_pix=%s, value_bradesco=%s,
        value_brv=%s, value_prefeitura=%s, position_order=%s WHERE id=%s""",
        (body.name, body.value_cash or 0, body.value_card_pix or 0, body.value_bradesco or 0,
        body.value_brv or 0, body.value_prefeitura or 0, body.position_order, proc_id)
    )
    db.commit()
    return {"ok": True}

@app.delete("/api/price-procedures/{proc_id}")
def delete_price_procedure(proc_id: str, user=Depends(require_level(1)), db=Depends(get_db)):
    db.execute("DELETE FROM price_procedures WHERE id=%s", (proc_id,))
    db.commit()
    return {"ok": True}

# ── CALENDAR EVENTS ───────────────────────────────────────────────────────────

@app.get("/api/calendar")
def get_calendar_events(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM calendar_events ORDER BY start_date ASC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/calendar")
def create_calendar_event(body: CalendarEventRequest, user=Depends(get_current_user), db=Depends(get_db)):
    event_id = str(uuid.uuid4())
    db.execute("""INSERT INTO calendar_events
        (id, title, description, location, color, start_date, end_date, all_day, is_public, repeat_type, created_by, created_at, user_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (event_id, body.title, body.description or "", body.location or "", body.color or "#C9A84C",
        body.start_date, body.end_date, 1 if body.all_day else 0, 1 if body.is_public else 0,
        body.repeat_type or "none", user["key"], datetime.datetime.utcnow().isoformat(), user["key"])
    )
    log_audit(db, user["key"], "calendar_create", user["key"],
              f"Evento criado: {body.title}")
    db.commit()
    return {"ok": True, "id": event_id}

@app.put("/api/calendar/{event_id}")
def update_calendar_event(event_id: str, body: CalendarEventRequest, user=Depends(get_current_user), db=Depends(get_db)):
    event = db.execute("SELECT * FROM calendar_events WHERE id=%s", (event_id,)).fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    if event["user_key"] != user["key"] and not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Você só pode editar seus próprios eventos.")
    db.execute("""UPDATE calendar_events SET title=%s, description=%s, location=%s, color=%s,
        start_date=%s, end_date=%s, all_day=%s, is_public=%s, repeat_type=%s WHERE id=%s""",
        (body.title, body.description or "", body.location or "", body.color or "#C9A84C",
        body.start_date, body.end_date, 1 if body.all_day else 0, 1 if body.is_public else 0,
        body.repeat_type or "none", event_id)
    )
    log_audit(db, user["key"], "calendar_update", event["user_key"],
              f"Evento atualizado: {body.title}")
    db.commit()
    return {"ok": True}

@app.delete("/api/calendar/{event_id}")
def delete_calendar_event(event_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    event = db.execute("SELECT * FROM calendar_events WHERE id=%s", (event_id,)).fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado.")
    if event["user_key"] != user["key"] and not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Você só pode remover seus próprios eventos.")
    db.execute("DELETE FROM calendar_events WHERE id=%s", (event_id,))
    log_audit(db, user["key"], "calendar_delete", event["user_key"],
              f"Evento removido: {event.get('title', '')}")
    db.commit()
    return {"ok": True}
# ── GAMIFICAÇÃO (PONTOS, BADGES, LEADERBOARD) ──────────────────────────────

@app.post("/api/gamificacao/add-points")
def add_points(user_key: str, points: int, reason: str, action_type: str, user=Depends(require_level(2)), db=Depends(get_db)):
    """Admin adiciona pontos a um usuário"""
    target = db.execute("SELECT * FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Adicionar ponto à tabela user_points
    point_id = str(uuid.uuid4())
    db.execute("""INSERT INTO user_points (id, user_key, points, reason, action_type, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (point_id, user_key, points, reason, action_type, datetime.datetime.utcnow().isoformat())
    )

    # Atualizar pontos totais do usuário
    current_points = target["points"] or 0
    new_total = current_points + points
    db.execute("UPDATE users SET points=%s WHERE key=%s", (new_total, user_key))

    _notify(db, title="💰 Pontos recebidos",
            message=f"Você recebeu {points} pontos por: {reason}",
            ntype="xp", target_user_key=user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=point_id, play_sound=True)
    db.commit()
    return {"ok": True, "new_total": new_total, "points_added": points}

@app.get("/api/gamificacao/user-points/{user_key}")
def get_user_points(user_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Obter pontos totais de um usuário"""
    target = db.execute("SELECT key, name, points FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Histórico de pontos
    history = db.execute("SELECT * FROM user_points WHERE user_key=%s ORDER BY created_at DESC LIMIT 50",
                        (user_key,)).fetchall()

    return {
        "user_key": target["key"],
        "name": target["name"],
        "total_points": target["points"] or 0,
        "history": [dict(h) for h in history]
    }

@app.post("/api/gamificacao/award-badge")
def award_badge(user_key: str, badge_type: str, badge_name: str, description: str, icon: str,
                user=Depends(require_level(2)), db=Depends(get_db)):
    """Admin concede uma badge a um usuário"""
    target = db.execute("SELECT * FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Verificar se já tem essa badge
    existing = db.execute("SELECT 1 FROM user_badges WHERE user_key=%s AND badge_type=%s",
                        (user_key, badge_type)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Usuário já tem essa badge")

    badge_id = str(uuid.uuid4())
    db.execute("""INSERT INTO user_badges (id, user_key, badge_type, badge_name, description, icon, earned_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (badge_id, user_key, badge_type, badge_name, description, icon, datetime.datetime.utcnow().isoformat())
    )

    _notify(db, title="🏅 Nova badge!",
            message=f"Você recebeu a badge {badge_name}: {description}",
            ntype="system", target_user_key=user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=badge_id, play_sound=True)
    db.commit()
    return {"ok": True, "badge_id": badge_id}

@app.get("/api/gamificacao/user-badges/{user_key}")
def get_user_badges(user_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Obter todas as badges de um usuário"""
    target = db.execute("SELECT key, name FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    badges = db.execute("SELECT * FROM user_badges WHERE user_key=%s ORDER BY earned_at DESC",
                    (user_key,)).fetchall()

    return {
        "user_key": target["key"],
        "name": target["name"],
        "badges": [dict(b) for b in badges],
        "total_badges": len(badges)
    }

@app.get("/api/gamificacao/leaderboard")
def get_leaderboard(month: str = None, user=Depends(get_current_user), db=Depends(get_db)):
    """Obter leaderboard do mês (ou geral se não especificado)"""
    import calendar

    if not month:
        # Usar mês atual
        now = datetime.datetime.utcnow()
        month = f"{now.year}-{str(now.month).zfill(2)}"

    # Buscar ranking mensal
    rows = db.execute("""
        SELECT mr.user_key, mr.points, mr.position, u.name, u.initials, u.color
        FROM monthly_ranking mr
        JOIN users u ON u.key = mr.user_key
        WHERE mr.month=%s
        ORDER BY mr.position ASC
    """, (month,)).fetchall()

    if not rows:
        # Se não tem dados do mês, usar pontos totais dos usuários
        rows = db.execute("""
            SELECT key as user_key, points, name, initials, color, 1 as position
            FROM users
            WHERE points > 0
            ORDER BY points DESC
        """).fetchall()

        result = []
        for idx, row in enumerate(rows, 1):
            result.append({
                "position": idx,
                "user_key": dict(row)["user_key"],
                "name": dict(row)["name"],
                "initials": dict(row)["initials"],
                "color": dict(row)["color"],
                "points": dict(row)["points"]
            })

        return {
            "month": month,
            "leaderboard": result,
            "total_users": len(result)
        }

    result = [
        {
            "position": dict(r)["position"],
            "user_key": dict(r)["user_key"],
            "name": dict(r)["name"],
            "initials": dict(r)["initials"],
            "color": dict(r)["color"],
            "points": dict(r)["points"]
        }
        for r in rows
    ]

    return {
        "month": month,
        "leaderboard": result,
        "total_users": len(result)
    }

@app.post("/api/gamificacao/update-monthly-ranking")
def update_monthly_ranking(user=Depends(require_level(3)), db=Depends(get_db)):
    """Admin recalcula o ranking mensal (rodar 1x por mês)"""
    import calendar

    now = datetime.datetime.utcnow()
    month = f"{now.year}-{str(now.month).zfill(2)}"

    # Buscar todos os usuários com seus pontos
    users = db.execute("SELECT key, points FROM users WHERE points > 0 ORDER BY points DESC").fetchall()

    # Limpar ranking anterior do mês
    db.execute("DELETE FROM monthly_ranking WHERE month=%s", (month,))

    # Inserir novo ranking
    for position, user_row in enumerate(users, 1):
        ranking_id = str(uuid.uuid4())
        db.execute("""INSERT INTO monthly_ranking (id, user_key, points, position, month, year, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (ranking_id, user_row["key"], user_row["points"], position, month, now.year, datetime.datetime.utcnow().isoformat())
        )

    db.commit()
    return {"ok": True, "month": month, "users_ranked": len(users)}

@app.post("/api/gamificacao/unlock-achievement")
def unlock_achievement(user_key: str, achievement_type: str, achievement_name: str, description: str, icon: str,
                    user=Depends(require_level(2)), db=Depends(get_db)):
    """Conceder uma conquista (achievement) a um usuário"""
    target = db.execute("SELECT * FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Verificar se já tem essa conquista
    existing = db.execute("SELECT 1 FROM user_achievements WHERE user_key=%s AND achievement_type=%s",
                        (user_key, achievement_type)).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Usuário já tem essa conquista")

    achievement_id = str(uuid.uuid4())
    db.execute("""INSERT INTO user_achievements (id, user_key, achievement_type, achievement_name, description, icon, unlocked_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (achievement_id, user_key, achievement_type, achievement_name, description, icon, datetime.datetime.utcnow().isoformat())
    )

    _notify(db, title="🏆 Conquista desbloqueada!",
            message=f"Você desbloqueou a conquista {achievement_name}: {description}",
            ntype="system", target_user_key=user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=achievement_id, play_sound=True)
    db.commit()
    return {"ok": True, "achievement_id": achievement_id}

@app.get("/api/gamificacao/user-achievements/{user_key}")
def get_user_achievements(user_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Obter todas as conquistas de um usuário"""
    target = db.execute("SELECT key, name FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    achievements = db.execute("SELECT * FROM user_achievements WHERE user_key=%s ORDER BY unlocked_at DESC",
                            (user_key,)).fetchall()

    return {
        "user_key": target["key"],
        "name": target["name"],
        "achievements": [dict(a) for a in achievements],
        "total_achievements": len(achievements)
    }

@app.get("/api/gamificacao/dashboard/{user_key}")
def get_gamification_dashboard(user_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Dashboard completo de gamificação do usuário"""
    target = db.execute("SELECT * FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    # Pontos totais
    total_points = target["points"] or 0

    # Badges
    badges = db.execute("SELECT * FROM user_badges WHERE user_key=%s", (user_key,)).fetchall()

    # Conquistas
    achievements = db.execute("SELECT * FROM user_achievements WHERE user_key=%s", (user_key,)).fetchall()

    # Histórico de pontos (últimos 10)
    history = db.execute("SELECT * FROM user_points WHERE user_key=%s ORDER BY created_at DESC LIMIT 10",
                        (user_key,)).fetchall()

    # Posição no ranking (mês atual)
    import calendar
    now = datetime.datetime.utcnow()
    month = f"{now.year}-{str(now.month).zfill(2)}"

    ranking = db.execute("SELECT position FROM monthly_ranking WHERE user_key=%s AND month=%s",
                        (user_key, month)).fetchone()
    position = ranking["position"] if ranking else None

    return {
        "user_key": target["key"],
        "name": target["name"],
        "total_points": total_points,
        "badges_count": len(badges),
        "achievements_count": len(achievements),
        "current_position": position,
        "current_month": month,
        "badges": [dict(b) for b in badges],
        "achievements": [dict(a) for a in achievements],
        "recent_points": [dict(h) for h in history]
    }

# ─────────────────────────────────────────────────────────────────────────────
# FEEDBACK SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_feedback_tables(db):
    """Create feedback tables if not exist (idempotent)."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS feedbacks (
            id TEXT PRIMARY KEY,
            target_user_key TEXT NOT NULL,
            evaluator_key TEXT NOT NULL,
            evaluator_name TEXT NOT NULL,
            evaluator_sector TEXT NOT NULL,
            feedback_text TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 10),
            action TEXT NOT NULL CHECK (action IN ('add', 'remove')),
            points INTEGER NOT NULL CHECK (points >= 0 AND points <= 100),
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            target_user_id TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )
    """)


def _can_evaluate(user: dict) -> bool:
    """Only RH, admin, admin_user, or ouvidor can create feedback."""
    return bool(user.get('is_admin') or user.get('is_admin_user') or
                user.get('is_rh') or user.get('is_ouvidor'))


@app.get("/api/feedbacks/{target_key}")
def get_feedbacks(target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_feedback_tables(db)
    rows = db.execute(
        "SELECT * FROM feedbacks WHERE target_user_key=%s ORDER BY created_at DESC",
        (target_key,)
    ).fetchall()
    feedbacks = []
    is_owner = user["key"] == target_key
    for r in rows:
        row = dict(r)
        if not is_owner:
            row.pop("points", None)
            row.pop("action", None)
        feedbacks.append(row)
    return feedbacks


@app.post("/api/feedbacks")
def create_feedback(body: FeedbackRequest, user=Depends(get_current_user), db=Depends(get_db)):
    import uuid, datetime, re
    _ensure_feedback_tables(db)

    if not _can_evaluate(user):
        raise HTTPException(status_code=403, detail="Sem permissão para avaliar colaboradores")

    # Validate
    if not 1 <= body.rating <= 10:
        raise HTTPException(status_code=422, detail="Nota deve ser entre 1 e 10")
    if not 0 <= body.points <= 100:
        raise HTTPException(status_code=422, detail="Pontos devem ser entre 0 e 100")
    if body.action not in ("add", "remove"):
        raise HTTPException(status_code=422, detail="Ação inválida")

    safe_text = _sanitize_text(body.feedback_text)
    safe_sector = _sanitize_text(body.evaluator_sector)
    if not safe_text:
        raise HTTPException(status_code=422, detail="Feedback não pode ser vazio")

    # Check rate limit: 1 feedback por avaliador por colaborador a cada 6h
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=6)).isoformat()
    existing = db.execute(
        "SELECT id FROM feedbacks WHERE evaluator_key=%s AND target_user_key=%s AND created_at > %s",
        (user["key"], body.target_user_key, cutoff)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=429, detail="Aguarde 6 horas para avaliar este colaborador novamente")

    # Verify target exists
    target = db.execute("SELECT key, points FROM users WHERE key=%s", (body.target_user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    now = datetime.datetime.utcnow().isoformat()
    fid = str(uuid.uuid4())

    # Insert feedback
    db.execute(
        """INSERT INTO feedbacks
        (id, target_user_key, evaluator_key, evaluator_name, evaluator_sector,
            feedback_text, rating, action, points, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (fid, body.target_user_key, user["key"], user["name"],
        safe_sector, safe_text, body.rating, body.action, body.points, now)
    )

    # Update XP
    current_xp = target["points"] or 0
    delta = body.points if body.action == "add" else -body.points
    new_xp = max(0, current_xp + delta)
    db.execute("UPDATE users SET points=%s WHERE key=%s", (new_xp, body.target_user_key))

    # Audit log
    db.execute(
        """INSERT INTO audit_log (id, actor_id, action, target_user_id, detail, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), user["key"],
        f"feedback_{body.action}_points",
        body.target_user_key,
        f"rating={body.rating} points={body.points if body.action=='add' else -body.points}",
        now)
    )

    # ── Notification triggers ──
    action_label = f"+{body.points} XP" if body.action == "add" else f"-{body.points} XP"
    _notify(db, title="⭐ Avaliação recebida",
            message=f"{user['name']} avaliou você com nota {body.rating}/10 ({action_label})",
            ntype="feedback", target_user_key=body.target_user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=fid, play_sound=True)
    xp_title = "💰 XP adicionado" if body.action == "add" else "📉 XP reduzido"
    xp_msg = (f"Você ganhou {body.points} XP." if body.action == "add"
            else f"Você perdeu {body.points} XP.") + f" Total: {new_xp} XP"
    _notify(db, title=xp_title, message=xp_msg,
            ntype="xp", target_user_key=body.target_user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=fid, play_sound=True)
    # Rank change detection
    _RANK_THRESHOLDS = [(0,49,"Aspirante"),(50,149,"Motivado"),(150,299,"Engajado"),
        (300,499,"Competidor"),(500,699,"Destaque"),(700,899,"Referência"),
        (900,999,"Elite"),(1000,9999999,"Lenda")]
    def _get_rank(xp):
        return next((r[2] for r in _RANK_THRESHOLDS if r[0] <= xp <= r[1]), "Aspirante")
    old_rank = _get_rank(current_xp)
    new_rank  = _get_rank(new_xp)
    if old_rank != new_rank:
        _notify(db, title="🏆 Novo rank alcançado!",
                message=f"Parabéns! Você alcançou o rank {new_rank}",
                ntype="system", target_user_key=body.target_user_key,
                sender_key=user["key"], sender_name=user["name"], play_sound=True)
    old_level = current_xp // 100
    new_level  = new_xp // 100
    if new_level > old_level:
        _notify(db, title="⬆️ Subiu de nível!",
                message=f"Você subiu para o Nível {new_level}!",
                ntype="system", target_user_key=body.target_user_key, play_sound=True)
    return {"ok": True, "feedback_id": fid, "new_xp": new_xp}


# ── MÉTRICAS ──────────────────────────────────────────────────────────────────

@app.get("/api/metricas/celebracoes")
def get_metric_celebracoes(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM celebracoes WHERE target_user_key=%s",
        (user["key"],)
    ).fetchone()
    return {"count": row["cnt"] if row else 0}

@app.get("/api/metricas/feedbacks")
def get_metric_feedbacks(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_feedback_tables(db)
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM feedbacks WHERE target_user_key=%s",
        (user["key"],)
    ).fetchone()
    return {"count": row["cnt"] if row else 0}

@app.get("/api/metricas/objetivos")
def get_metric_objetivos(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM objetivos WHERE user_key=%s",
        (user["key"],)
    ).fetchone()
    return {"count": row["cnt"] if row else 0}

@app.get("/api/metricas/pesquisas")
def get_metric_pesquisas(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM pesquisas WHERE user_key=%s",
        (user["key"],)
    ).fetchone()
    return {"count": row["cnt"] if row else 0}


# ── TAREFAS ───────────────────────────────────────────────────────────────────

@app.get("/api/tarefas/hoje")
def get_tarefas_hoje(user=Depends(get_current_user), db=Depends(get_db)):
    hoje = datetime.date.today().isoformat()

    # Tarefas persistidas do usuário: pendentes (qualquer prazo) + concluídas recentes
    tarefas = db.execute(
        """SELECT t.*, u.name AS destinatario_nome, u.initials AS destinatario_initials,
                  u.color AS destinatario_color,
                  c.name AS criador_nome
           FROM tarefas t
           LEFT JOIN users u ON u.key = t.destinatario_id
           LEFT JOIN users c ON c.key = t.criado_por
           WHERE t.destinatario_id = %s AND (t.concluida = 0 OR t.prazo >= %s)
           ORDER BY t.prazo ASC, t.created_at DESC""",
        (user["key"], hoje)
    ).fetchall()

    result = [dict(t) for t in tarefas]

    # Tarefas de aniversário geradas automaticamente
    today_md = datetime.date.today().strftime("%m-%d")
    aniversariantes = db.execute(
        "SELECT key, name, initials, color FROM users WHERE SUBSTRING(birth_date, 6, 5) = %s",
        (today_md,)
    ).fetchall()

    for aniv in aniversariantes:
        # Verificar se já enviou celebração hoje para esse aniversariante
        celeb_hoje = db.execute(
            "SELECT COUNT(*) as cnt FROM celebracoes WHERE author_key=%s AND target_user_key=%s AND DATE(created_at)=%s",
            (user["key"], aniv["key"], hoje)
        ).fetchone()
        concluida = (celeb_hoje["cnt"] if celeb_hoje else 0) > 0

        result.append({
            "id": f"aniversario_{aniv['key']}",
            "titulo": f"Celebrar {aniv['name']}",
            "descricao": "Aniversário hoje — envie uma celebração e ganhe DCoins",
            "tipo": "aniversario",
            "destinatario_id": aniv["key"],
            "destinatario_nome": aniv["name"],
            "destinatario_initials": aniv["initials"],
            "destinatario_color": aniv["color"],
            "prazo": hoje,
            "concluida": concluida,
            "criado_por": None,
            "criador_nome": None,
        })

    return result


def _is_gestor(user: dict) -> bool:
    return bool(
        user.get("is_admin") or
        user.get("is_admin_user") or
        user.get("is_rh") or
        user.get("is_diretor") or
        user.get("is_leader") or
        user.get("org_position") in ("gestor", "lider")
    )


@app.post("/api/tarefas")
def criar_tarefa(body: CriarTarefaRequest, user=Depends(get_current_user), db=Depends(get_db)):
    safe_titulo = _sanitize_text(body.titulo)
    safe_descricao = _sanitize_text(body.descricao) if body.descricao else ""
    if not safe_titulo:
        raise HTTPException(status_code=422, detail="Título é obrigatório.")

    hoje = datetime.date.today().isoformat()
    prazo = body.prazo
    if prazo < hoje:
        raise HTTPException(status_code=422, detail="Prazo não pode ser no passado.")

    destinatarios = body.destinatarios or []
    if not destinatarios:
        destinatarios = [user["key"]]

    # Se tentar atribuir para outra pessoa, precisa ser gestor
    outros = [k for k in destinatarios if k != user["key"]]
    if outros and not _is_gestor(user):
        raise HTTPException(status_code=403, detail="Apenas gestores podem atribuir tarefas para outras pessoas.")

    now = datetime.datetime.utcnow().isoformat()
    created = []
    for dest_key in destinatarios:
        dest = db.execute("SELECT key FROM users WHERE key=%s", (dest_key,)).fetchone()
        if not dest:
            continue
        tid = str(uuid.uuid4())
        db.execute(
            """INSERT INTO tarefas (id, titulo, descricao, tipo, criado_por, destinatario_id, prazo, concluida, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)""",
            (tid, safe_titulo, safe_descricao, "gestor", user["key"], dest_key, prazo, now, now)
        )
        created.append(tid)
        if dest_key != user["key"]:
            _notify(db, title="📋 Nova tarefa atribuída",
                    message=f"{user['name']} atribuiu a tarefa: {safe_titulo}",
                    ntype="system", target_user_key=dest_key,
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=tid, play_sound=True)

    db.commit()
    return {"ok": True, "tarefas_criadas": len(created), "ids": created}


@app.patch("/api/tarefas/{tarefa_id}/concluir")
def concluir_tarefa(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["destinatario_id"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode concluir uma tarefa que não é sua.")

    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE tarefas SET concluida=1, concluida_em=%s, updated_at=%s WHERE id=%s",
        (now, now, tarefa_id)
    )

    tipo_atv = "tarefa_gestor" if tarefa.get("tipo") == "gestor" else "tarefa_rotina"
    _log_atividade(db, tipo_atv, user["key"],
                   f"{user['name']} concluiu {'uma Tarefa do Gestor' if tipo_atv == 'tarefa_gestor' else 'uma Tarefa'}")

    db.commit()
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATION SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_notifications_table(db):
    """Idempotent — create notifications table + indexes if not exist."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            type TEXT NOT NULL,
            target_user_key TEXT NULL,
            audience TEXT NULL DEFAULT 'personal',
            sender_key TEXT NULL,
            sender_name TEXT NULL,
            reference_id TEXT NULL,
            play_sound BOOLEAN DEFAULT FALSE,
            is_read BOOLEAN DEFAULT FALSE,
            created_at TEXT NOT NULL
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_notif_target ON notifications(target_user_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_notif_audience ON notifications(audience)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_notif_read ON notifications(is_read)")


def _notify(db, *, title: str, message: str, ntype: str,
            target_user_key: str = None, audience: str = None,
            sender_key: str = None, sender_name: str = None,
            reference_id: str = None, play_sound: bool = False):
    """Insert a notification. Call after the main operation succeeds."""
    import uuid, datetime
    _ensure_notifications_table(db)
    db.execute(
        """INSERT INTO notifications
        (id, title, message, type, target_user_key, audience,
            sender_key, sender_name, reference_id, play_sound, is_read, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), title, message, ntype,
        target_user_key, audience or ('personal' if target_user_key else 'all'),
        sender_key, sender_name, reference_id, play_sound, False,
        datetime.datetime.utcnow().isoformat())
    )


def _extract_mentions(text: str):
    """Return list of @keys found in text."""
    import re
    return re.findall(r'@([A-Za-z0-9_]+)', text or '')


# ── GET notifications ─────────────────────────────────────────────────────────
@app.get("/api/notifications")
def get_notifications(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_notifications_table(db)
    rows = db.execute(
        """SELECT * FROM notifications
        WHERE target_user_key = %s
            OR audience = 'all'
            OR audience = %s
        ORDER BY created_at DESC
        LIMIT 40""",
        (user["key"], user.get("dept", ""))
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/notifications/unread-count")
def get_unread_count(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_notifications_table(db)
    row = db.execute(
        """SELECT COUNT(*) as cnt FROM notifications
        WHERE is_read = FALSE
            AND (target_user_key = %s OR audience = 'all' OR audience = %s)""",
        (user["key"], user.get("dept", ""))
    ).fetchone()
    return {"count": row["cnt"] if row else 0}


@app.post("/api/notifications/{notif_id}/read")
def mark_read(notif_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_notifications_table(db)
    # Only mark if notification belongs to this user
    db.execute(
        """UPDATE notifications SET is_read = TRUE
        WHERE id = %s
            AND (target_user_key = %s OR audience = 'all' OR audience = %s)""",
        (notif_id, user["key"], user.get("dept", ""))
    )
    return {"ok": True}


@app.post("/api/notifications/read-all")
def mark_all_read(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_notifications_table(db)
    db.execute(
        """UPDATE notifications SET is_read = TRUE
        WHERE is_read = FALSE
            AND (target_user_key = %s OR audience = 'all' OR audience = %s)""",
        (user["key"], user.get("dept", ""))
    )
    return {"ok": True}


# ── Helper: extrai iniciais de um nome ─────────────────────────────────────
def _get_initials(name: str):
    if not name:
        return "??"
    parts = name.strip().split()
    iniciais = "".join(p[0] for p in parts if p and p[0].isalpha())[:2].upper()
    return iniciais or "??"


# ── Helper: cor deterministic a partir do nome ──────────────────────────────
_NOTIF_COLORS = ["#c0395a", "#b8842a", "#7b4fa6", "#2e7d6e",
                  "#1a5fa3", "#d4537e", "#639922", "#ba7517"]

def _get_actor_color(name: str):
    if not name:
        return "#c0395a"
    h = sum(ord(c) for c in name)
    return _NOTIF_COLORS[h % len(_NOTIF_COLORS)]


# ── GET /api/notifications/v2 — retorna notificacoes no novo formato ────────
@app.get("/api/notifications/v2")
def get_notifications_v2(
    type: str = None,
    read: str = None,
    limit: int = 50,
    offset: int = 0,
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    _ensure_notifications_table(db)
    conditions = ["(n.target_user_key = %s OR n.audience = 'all' OR n.audience = %s)"]
    params = [user["key"], user.get("dept", "")]

    if type:
        conditions.append("n.type = %s")
        params.append(type)
    if read is not None:
        if read.lower() == "true":
            conditions.append("n.is_read = TRUE")
        elif read.lower() == "false":
            conditions.append("n.is_read = FALSE")

    where = " AND ".join(conditions)
    rows = db.execute(
        f"""SELECT n.*,
            u.initials AS actor_initials,
            u.color   AS actor_color
            FROM notifications n
            LEFT JOIN users u ON n.sender_key = u.key
            WHERE {where}
            ORDER BY n.created_at DESC
            LIMIT %s OFFSET %s""",
        params + [limit, offset]
    ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        actor_name = d.get("sender_name") or "Sistema"
        result.append({
            "id": d["id"],
            "type": d["type"],
            "read": d["is_read"],
            "created_at": d["created_at"],
            "actor": {
                "id": d.get("sender_key"),
                "name": actor_name,
                "avatar_url": None,
                "initials": d.get("actor_initials") or _get_initials(actor_name),
                "color": d.get("actor_color") or _get_actor_color(actor_name),
            },
            "action": d.get("title", ""),
            "target": d.get("message", ""),
            "target_type": None,
            "link": d.get("reference_id"),
        })

    return result


# ── PATCH /api/notifications/{notif_id}/read ─────────────────────────────────
@app.patch("/api/notifications/{notif_id}/read")
def mark_read_patch(notif_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_notifications_table(db)
    db.execute(
        """UPDATE notifications SET is_read = TRUE
        WHERE id = %s
            AND (target_user_key = %s OR audience = 'all' OR audience = %s)""",
        (notif_id, user["key"], user.get("dept", ""))
    )
    return {"success": True}


# ── PATCH /api/notifications/read-all ────────────────────────────────────────
@app.patch("/api/notifications/read-all")
def mark_all_read_patch(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_notifications_table(db)
    cur = db.execute(
        """UPDATE notifications SET is_read = TRUE
        WHERE is_read = FALSE
            AND (target_user_key = %s OR audience = 'all' OR audience = %s)""",
        (user["key"], user.get("dept", ""))
    )
    updated = cur.rowcount if hasattr(cur, 'rowcount') else 0
    return {"success": True, "updated": updated}


    # ============================================================
# COLE ESSAS ROTAS NO FINAL DO SEU main.py
# ============================================================
#
# ANTES: rode esse SQL no seu banco Neon para adicionar
# as colunas e a tabela necessárias:
#
# ALTER TABLE users ADD COLUMN IF NOT EXISTS manager_key TEXT DEFAULT NULL;
# ALTER TABLE users ADD COLUMN IF NOT EXISTS org_position TEXT DEFAULT 'colaborador';
#   -- valores possíveis: 'colaborador', 'lider', 'gestor'
#
# ============================================================

from pydantic import BaseModel
from typing import Optional, List

# ---------- Models ----------

class AssignManagerRequest(BaseModel):
    """Admin define o gestor de um usuário"""
    target_user_key: str          # usuário que vai receber o gestor
    manager_key: Optional[str]    # chave do gestor (None = remover gestor)

class AssignTeamRequest(BaseModel):
    """Admin define a equipe de um usuário"""
    target_user_key: str          # usuário que vai receber a equipe
    member_keys: List[str]        # lista de chaves dos membros da equipe

class SetOrgPositionRequest(BaseModel):
    """Admin define a posição organizacional de um usuário"""
    target_user_key: str
    org_position: str             # 'colaborador' | 'lider' | 'gestor'


# ---------- Helpers ----------

def _require_admin(user: dict):
    """Garante que só admin ou admin_user acessa"""
    if not (user.get("is_admin") or user.get("is_admin_user")):
        raise HTTPException(status_code=403, detail="Acesso negado. Apenas admins.")


def _safe_user(row) -> dict:
    """Converte row em dict removendo campos sensíveis"""
    d = dict(row)
    d.pop("password_hash", None)
    d.pop("password_changed", None)
    return d


# ---------- Rotas ----------

@app.get("/api/users/gestores")
def list_gestores(user=Depends(get_current_user), db=Depends(get_db)):
    """
    Retorna todos os usuários com org_position IN ('lider', 'gestor').
    Usado no dropdown de seleção de gestor no frontend.
    """
    rows = db.execute(
        """SELECT key, name, role, dept, photo_url, org_position
        FROM users
        WHERE org_position IN ('lider', 'gestor')
        ORDER BY name"""
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/users/{target_key}/manager")
def get_user_manager(target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    """
    Retorna o gestor atual do usuário alvo.
    """
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    manager_key = target["manager_key"] if "manager_key" in target.keys() else None
    if not manager_key:
        return {"manager": None}

    manager = db.execute(
        "SELECT key, name, role, dept, photo_url FROM users WHERE key=%s",
        (manager_key,)
    ).fetchone()
    return {"manager": dict(manager) if manager else None}


@app.put("/api/users/assign-manager")
def assign_manager(body: AssignManagerRequest, user=Depends(get_current_user), db=Depends(get_db)):
    """
    Admin define (ou remove) o gestor de um usuário.
    """
    _require_admin(user)

    target = db.execute("SELECT * FROM users WHERE key=%s", (body.target_user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário alvo não encontrado.")

    if body.manager_key:
        manager = db.execute("SELECT * FROM users WHERE key=%s", (body.manager_key,)).fetchone()
        if not manager:
            raise HTTPException(status_code=404, detail="Gestor não encontrado.")
        if manager["org_position"] not in ("lider", "gestor"):
            raise HTTPException(status_code=400, detail="Usuário selecionado não é gestor ou líder.")

    db.execute(
        "UPDATE users SET manager_key=%s WHERE key=%s",
        (body.manager_key, body.target_user_key)
    )
    db.commit()

    log_action(
        db, user["key"], body.target_user_key,
        "Atribuição de Gestor",
        f"Gestor definido: {body.manager_key or 'removido'}"
    )
    return {"ok": True}


@app.get("/api/users/{target_key}/team")
def get_user_team(target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    """
    Retorna a equipe do usuário:
    - Se for 'gestor': retorna todos que têm manager_key = target_key
    - Se for 'lider': retorna todos que têm manager_key = target_key (seus subordinados)
    - Se for 'colaborador': retorna colegas (mesmo gestor, excluindo ele mesmo)
    """
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    org_position = target["org_position"] if "org_position" in target.keys() else "colaborador"
    manager_key = target["manager_key"] if "manager_key" in target.keys() else None

    if org_position in ("gestor", "lider"):
        # Subordinados diretos
        rows = db.execute(
            """SELECT key, name, role, dept, photo_url, org_position
            FROM users
            WHERE manager_key=%s
            ORDER BY name""",
            (target_key,)
        ).fetchall()
        return {
            "type": "subordinados",
            "members": [dict(r) for r in rows]
        }
    else:
        # Colaborador: mostra colegas com mesmo gestor
        if not manager_key:
            return {"type": "equipe", "members": []}

        rows = db.execute(
            """SELECT key, name, role, dept, photo_url, org_position
            FROM users
            WHERE manager_key=%s AND key != %s
            ORDER BY name""",
            (manager_key, target_key)
        ).fetchall()
        return {
            "type": "equipe",
            "members": [dict(r) for r in rows]
        }


@app.put("/api/users/set-org-position")
def set_org_position(body: SetOrgPositionRequest, user=Depends(get_current_user), db=Depends(get_db)):
    """
    Admin define a posição organizacional de um usuário.
    Valores: 'colaborador' | 'lider' | 'gestor'
    """
    _require_admin(user)

    if body.org_position not in ("colaborador", "lider", "gestor"):
        raise HTTPException(status_code=400, detail="org_position inválido. Use: colaborador, lider ou gestor.")

    target = db.execute("SELECT * FROM users WHERE key=%s", (body.target_user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    db.execute(
        "UPDATE users SET org_position=%s WHERE key=%s",
        (body.org_position, body.target_user_key)
    )
    db.commit()

    log_action(
        db, user["key"], body.target_user_key,
        "Posição Organizacional",
        f"org_position definido como: {body.org_position}"
    )
    return {"ok": True}