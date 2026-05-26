from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, status, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import os, uuid, shutil, datetime, json, re, time
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import logging

from pydantic import BaseModel

from models import *
from database import get_db, init_db, get_db_context
from auth import create_token, verify_token, hash_password, check_password

import cloudinary
import cloudinary.uploader
import socketio


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
_birthday_limits = {}
_activity_limits = {}
_objective_limits = {}
_idempotency_keys = {}
logger = logging.getLogger("dialogos.security")

def _check_upload_rate_limit(user_key: str):
    now = time.time()
    minute = int(now / 60)
    key = f"{user_key}:{minute}"
    count = _upload_limits.get(key, 0)
    if count >= 10:
        raise HTTPException(status_code=429, detail="Limite de uploads excedido. Tente novamente em 1 minuto.")
    _upload_limits[key] = count + 1

def _check_birthday_rate_limit(user_key: str):
    now = time.time()
    minute = int(now / 60)
    key = f"{user_key}:{minute}"
    count = _birthday_limits.get(key, 0)
    if count >= 60:
        raise HTTPException(status_code=429, detail="Limite de requisições excedido. Tente novamente em instantes.")
    _birthday_limits[key] = count + 1

def _check_activity_rate_limit(user_key: str):
    now = time.time()
    minute = int(now / 60)
    key = f"{user_key}:{minute}"
    count = _activity_limits.get(key, 0)
    if count >= 120:
        raise HTTPException(status_code=429, detail="Limite de requisições excedido. Tente novamente em instantes.")
    _activity_limits[key] = count + 1

def _sanitize_html(html: str) -> str:
    """Whitelist-based HTML sanitizer for rich text content (Comunicados)."""
    if not html:
        return ""
    ALLOWED_TAGS = {
        'p', 'br', 'b', 'i', 'u', 'em', 'strong', 'small', 'sub', 'sup',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'hr',
        'a', 'img',
        'div', 'span',
        'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'caption',
    }
    ALLOWED_ATTRS = {
        'a': ['href', 'title', 'target', 'rel'],
        'img': ['src', 'alt', 'title', 'width', 'height', 'style'],
        '*': ['class', 'style', 'id'],
    }
    ALLOWED_PROTOCOLS = {'http', 'https', 'mailto'}
    # Remove dangerous patterns first
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
        html = re.sub(pattern, '', html, flags=re.IGNORECASE)
    # Strip tags not in whitelist
    def _strip_disallowed(m):
        tag = m.group(0)
        tagname = re.match(r'</?(\w+)', tag).group(1).lower()
        if tagname in ALLOWED_TAGS:
            return tag
        return ''
    html = re.sub(r'<[^>]*>', _strip_disallowed, html)
    # Strip dangerous attributes
    def _clean_attrs(m):
        tag = m.group(0)
        tagname = re.match(r'</?(\w+)', tag).group(1).lower() if not tag.startswith('</') else ''
        if tag.startswith('</'):
            return tag
        allowed_attrs = ALLOWED_ATTRS.get(tagname, []) + ALLOWED_ATTRS.get('*', [])
        new_tag = re.match(r'<\w+', tag).group(0)
        for attr, value in re.findall(r'(\w+)\s*=\s*"([^"]*)"', tag):
            if attr in allowed_attrs:
                if attr in ('href', 'src'):
                    protocol = value.split(':')[0].lower() if ':' in value else 'http'
                    if protocol in ALLOWED_PROTOCOLS:
                        new_tag += f' {attr}="{value}"'
                elif attr == 'style':
                    safe_style = re.sub(r'(?i)(position|absolute|fixed|z-index|top|left|display).*?(;|$)', '', value)
                    if safe_style.strip():
                        new_tag += f' style="{safe_style.strip()}"'
                else:
                    new_tag += f' {attr}="{value}"'
        new_tag += '>'
        return new_tag
    html = re.sub(r'<[^>]+>', _clean_attrs, html)
    return html.strip()[:150000]  # 150KB max

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
        "https://axis-dialogos.vercel.app"
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

# Socket.IO server (real-time updates without polling)
sio = socketio.Server(
    cors_allowed_origins=origins,
    logger=False,
    engineio_logger=False,
)

def _extract_socket_token(environ, auth):
    if isinstance(auth, dict) and auth.get("token"):
        return auth.get("token")
    header = environ.get("HTTP_AUTHORIZATION") or ""
    if header.startswith("Bearer "):
        return header[7:]
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    if qs.get("token"):
        return qs["token"][0]
    return None

_user_cache = {}
_USER_CACHE_TTL = 300

def _get_user_cache(user_key):
    entry = _user_cache.get(user_key)
    if entry and time.time() - entry["ts"] < _USER_CACHE_TTL:
        return entry["data"]
    _user_cache.pop(user_key, None)
    return None

def _set_user_cache(user_key, data):
    _user_cache[user_key] = {"data": data, "ts": time.time()}

def _invalidate_user_cache(user_key):
    _user_cache.pop(user_key, None)

_presence = {}
_PRESENCE_TIMEOUT = 60

def _presence_user_list():
    return sorted(_presence.values(), key=lambda u: u["name"].lower())

def _emit_presence():
    sio.emit("presence_update", {
        "online_count": len(_presence),
        "users": _presence_user_list(),
    }, room="all")

def _cleanup_stale_presence():
    now = time.time()
    stale = [k for k, v in list(_presence.items()) if now - v["last_ping"] > _PRESENCE_TIMEOUT]
    for k in stale:
        _presence.pop(k, None)
    if stale:
        _emit_presence()

@sio.event
def connect(sid, environ, auth=None):
    token = _extract_socket_token(environ, auth)
    if not token:
        raise ConnectionRefusedError("unauthorized")
    payload = verify_token(token)
    if not payload or not payload.get("sub"):
        raise ConnectionRefusedError("unauthorized")
    with get_db_context() as db:
        user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
        if not user_row:
            raise ConnectionRefusedError("unauthorized")
        user = dict(user_row)
    sio.save_session(sid, {
        "user_key": user["key"],
        "dept": user.get("dept", ""),
        "name": user["name"],
        "initials": user.get("initials", user["name"][0] if user["name"] else "?"),
        "color": user.get("color", "#C9A84C"),
        "photo_url": user.get("photo_url", ""),
        "role": user.get("role", ""),
    })
    sio.enter_room(sid, "all")
    sio.enter_room(sid, f"user:{user['key']}")
    if user.get("dept"):
        sio.enter_room(sid, f"dept:{user['dept']}")
    user_key = user["key"]
    now = time.time()
    if user_key in _presence:
        _presence[user_key]["count"] += 1
        _presence[user_key]["last_ping"] = now
    else:
        _presence[user_key] = {
            "user_key": user_key,
            "name": user["name"],
            "initials": user.get("initials", user["name"][0] if user["name"] else "?"),
            "color": user.get("color", "#C9A84C"),
            "photo_url": user.get("photo_url", ""),
            "role": user.get("role", ""),
            "last_ping": now,
            "count": 1,
        }
    _emit_presence()

@sio.event
def disconnect(sid):
    try:
        session = sio.get_session(sid)
    except Exception:
        session = None
    if session and session.get("user_key"):
        ukey = session["user_key"]
        entry = _presence.get(ukey)
        if entry:
            entry["count"] -= 1
            if entry["count"] <= 0:
                _presence.pop(ukey, None)
        _emit_presence()

@sio.event
def ping(sid):
    try:
        session = sio.get_session(sid)
    except Exception:
        session = None
    if session and session.get("user_key"):
        ukey = session["user_key"]
        if ukey in _presence:
            _presence[ukey]["last_ping"] = time.time()
    _cleanup_stale_presence()

@sio.event
def join(sid, data):
    room = (data or {}).get("room")
    if room:
        sio.enter_room(sid, room)

@sio.event
def leave(sid, data):
    room = (data or {}).get("room")
    if room:
        sio.leave_room(sid, room)

def ws_emit(event: str, payload: dict, rooms=None):
    try:
        if rooms:
            for room in rooms:
                sio.emit(event, payload, room=room)
            return
        sio.emit(event, payload, room="all")
    except Exception:
        logger.exception("socket_emit_failed event=%s", event)

def ws_emit_to_user(user_key: str, event: str, payload: dict):
    try:
        sio.emit(event, payload, room=f"user:{user_key}")
    except Exception:
        logger.exception("socket_emit_to_user_failed event=%s user=%s", event, user_key)

security = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            raise HTTPException(status_code=401, detail="Token ausente")
        payload = verify_token(credentials.credentials)
        if not payload:
            raise HTTPException(status_code=401, detail="Token inválido ou expirado")

        cached = _get_user_cache(payload["sub"])
        if cached:
            return cached

        with get_db_context() as db:
            user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
            if not user_row:
                raise HTTPException(status_code=401, detail="Usuário não encontrado")
            user_data = dict(user_row)
            _set_user_cache(payload["sub"], user_data)
            return user_data

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

    cached = _get_user_cache(payload["sub"])
    if cached:
        return cached

    with get_db_context() as db:
        user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
        if not user_row:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        user_data = dict(user_row)
        _set_user_cache(payload["sub"], user_data)
        return user_data

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
        auto_concluiu = _auto_concluir_login(db, user)
        return {
            "token": token,
            "must_change_password": not user["password_changed"],
            "auto_concluiu_login": auto_concluiu,
            "user": {
                "key": user["key"], "name": user["name"], "initials": user["initials"],
                "role": user["role"], "dept": user["dept"], "level": user["level"],
                "color": user["color"], "access_level": user["access_level"],
                "is_admin": bool(user["is_admin"]), "is_admin_user": bool(user["is_admin_user"]),
                "is_rh": bool(user["is_rh"]), "is_ouvidor": bool(user["is_ouvidor"]),
                "is_diretor": bool(user["is_diretor"]), "is_leader": bool(user["is_leader"]),
                "is_orcoma": bool(user["is_orcoma"]),
                "nivel_dourado": bool(user.get("nivel_dourado")),
                "org_position": user.get("org_position", "colaborador"),
                "points": user["points"], "photo_url": user["photo_url"],
            }
        }

@app.get("/api/auth/me")
def auth_me(user=Depends(get_current_user)):
    return {
        "key": user["key"], "name": user["name"], "initials": user["initials"],
        "role": user["role"], "dept": user["dept"], "level": user["level"],
        "color": user["color"], "access_level": user["access_level"],
        "is_admin": bool(user["is_admin"]), "is_admin_user": bool(user["is_admin_user"]),
        "is_rh": bool(user["is_rh"]), "is_ouvidor": bool(user["is_ouvidor"]),
        "is_diretor": bool(user["is_diretor"]), "is_leader": bool(user["is_leader"]),
        "is_orcoma": bool(user["is_orcoma"]),
        "nivel_dourado": bool(user.get("nivel_dourado")),
        "org_position": user.get("org_position", "colaborador"),
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
        _invalidate_user_cache(target_key)
        if user["key"] != target_key:
            _invalidate_user_cache(user["key"])
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
    _invalidate_user_cache(target_key)
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
        _invalidate_user_cache(user["key"])
        _notify(db, title="📸 Foto atualizada",
                message=f"{user['name']} atualizou sua foto de perfil",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                play_sound=False)
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/users/me/about")
def update_about_me(body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    about_text = (body or {}).get("text", "")
    db.execute("UPDATE users SET about_me=%s WHERE key=%s", (about_text, user["key"]))
    db.commit()
    _invalidate_user_cache(user["key"])
    return {"ok": True}


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
        ws_emit("new_post", {
            "id": post_id,
            "feed": body.feed,
            "author_key": user["key"],
            "author_name": user["name"],
            "author_initials": user["initials"],
            "author_color": user["color"],
            "author_photo_url": user.get("photo_url", ""),
            "author_role": user.get("role", ""),
            "author_is_rh": bool(user.get("is_rh")),
            "author_is_admin": bool(user.get("is_admin")),
            "text": safe_text,
            "image_url": safe_image,
            "video_url": safe_video,
            "embed_url": safe_embed,
            "access_level": body.access_level,
            "comunicado_tipo": body.comunicado_tipo,
            "pinned": 0,
            "likes": [],
            "comments": [],
            "created_at": datetime.datetime.utcnow().isoformat(),
        }, rooms=[f"feed:{body.feed}", "all"])
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
    feed = post["feed"]
    db.execute("DELETE FROM posts WHERE id=%s", (post_id,))
    db.commit()
    ws_emit("delete_post", {"id": post_id, "feed": feed}, rooms=[f"feed:{feed}", "all"])
    return {"ok": True}

@app.post("/api/posts/{post_id}/pin")
def pin_post(post_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404)
    new_pin = 0 if post["pinned"] else 1
    db.execute("UPDATE posts SET pinned=%s WHERE id=%s", (new_pin, post_id))
    db.commit()
    ws_emit("update_post", {"id": post_id, "feed": post["feed"], "pinned": new_pin}, rooms=[f"feed:{post['feed']}", "all"])
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
    ws_emit("update_post", {"id": post_id, "feed": post["feed"], "likes": likes}, rooms=[f"feed:{post['feed']}", "all"])
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
    ws_emit("update_post", {"id": post_id, "feed": post["feed"], "comments": comments}, rooms=[f"feed:{post['feed']}", "all"])
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

# ═════════════════════════════════════════════════════════════════════════════
# COMUNICADOS MODULE (institutional communications)
# ═════════════════════════════════════════════════════════════════════════════

_COMUNICADO_RATE_LIMITS = {}  # user_key -> list of publish timestamps for rate limiting

def _ensure_comunicados_table(db):
    db.execute("""
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
    db.execute("""
        CREATE TABLE IF NOT EXISTS communication_reads (
            id TEXT PRIMARY KEY,
            communication_id TEXT NOT NULL,
            user_key TEXT NOT NULL,
            read_at TEXT NOT NULL,
            read_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(communication_id, user_key)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS communication_notifications (
            id TEXT PRIMARY KEY,
            communication_id TEXT NOT NULL,
            notified_at TEXT NOT NULL,
            total_recipients INTEGER NOT NULL DEFAULT 0
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_author ON communications(author_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_published ON communications(is_published)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_deleted ON communications(is_deleted)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_audience ON communications(target_audience)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_created ON communications(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_reads_comm ON communication_reads(communication_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_comm_reads_user ON communication_reads(user_key)")


def _can_publish_comunicado(user) -> bool:
    role = (user.get("role") or "").lower()
    return bool(
        user.get("is_admin") or user.get("is_admin_user") or
        user.get("is_rh") or user.get("is_diretor") or user.get("is_leader") or
        role in ("diretora", "diretor", "líder", "lider", "admin", "rh")
    )


def _check_comunicado_rate_limit(user_key: str):
    now = time.time()
    if user_key not in _COMUNICADO_RATE_LIMITS:
        _COMUNICADO_RATE_LIMITS[user_key] = []
    timestamps = _COMUNICADO_RATE_LIMITS[user_key]
    # Keep only last hour
    cutoff = now - 3600
    timestamps[:] = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= 10:
        raise HTTPException(status_code=429, detail="Limite de 10 publicações por hora excedido.")
    timestamps.append(now)


def _comunicado_to_dict(row) -> dict:
    return {
        "id": row.get("id"),
        "title": _sanitize_text(row.get("title") or ""),
        "content": row.get("content") or "",
        "author_key": row.get("author_key"),
        "author_name": row.get("author_name"),
        "is_draft": bool(row.get("is_draft")),
        "is_published": bool(row.get("is_published")),
        "published_at": row.get("published_at"),
        "is_deleted": bool(row.get("is_deleted")),
        "deleted_at": row.get("deleted_at"),
        "deleted_by_key": row.get("deleted_by_key"),
        "target_audience": row.get("target_audience") or "all",
        "priority": row.get("priority") or "normal",
        "views_count": row.get("views_count") or 0,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }

def _comunicado_to_list_dict(row) -> dict:
    """Same as _comunicado_to_dict but WITHOUT content (for listing)."""
    d = _comunicado_to_dict(row)
    d.pop("content", None)
    return d


# ── CREATE comunicado ─────────────────────────────────────────────────────────
@app.post("/api/comunicados")
def criar_comunicado(body: CriarComunicadoRequest, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    if not _can_publish_comunicado(user):
        raise HTTPException(status_code=403, detail="Sem permissão para criar comunicados.")
    if not body.title or not body.title.strip():
        raise HTTPException(status_code=400, detail="Título é obrigatório.")
    if not body.content or not body.content.strip():
        raise HTTPException(status_code=400, detail="Conteúdo é obrigatório.")
    if body.priority not in ("normal", "urgent"):
        raise HTTPException(status_code=400, detail="Prioridade inválida. Use 'normal' ou 'urgent'.")
    if body.target_audience not in ("all", "rh", "leader", "admin", "diretor", "platina", "dourado", "diamante"):
        raise HTTPException(status_code=400, detail="Audiência inválida.")
    if len(body.content) > 150000:
        raise HTTPException(status_code=400, detail="Conteúdo excede o limite de 150KB.")
    now = datetime.datetime.utcnow().isoformat()
    safe_title = _sanitize_text(body.title.strip())[:200]
    safe_content = _sanitize_html(body.content)
    if not safe_content.strip():
        safe_content = body.content[:150000]
    comm_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO communications
        (id, title, content, author_key, author_name,
         is_draft, is_published, published_at,
         is_deleted, target_audience, priority, views_count,
         created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        comm_id, safe_title, safe_content,
        user["key"], user["name"],
        1 if body.is_draft else 0,
        0 if body.is_draft else 1,
        None if body.is_draft else now,
        0, body.target_audience, body.priority, 0,
        now, now,
    ))
    _log_atividade(db, "comunicado", user["key"],
                   f"{'Rascunho' if body.is_draft else 'Publicou'} comunicado: {safe_title[:100]}")
    db.commit()
    return {"ok": True, "id": comm_id}


# ── LIST comunicados ──────────────────────────────────────────────────────────
@app.get("/api/comunicados")
def listar_comunicados(
    user=Depends(get_current_user),
    db=Depends(get_db),
    filtro: str = "ativos",
    page: int = 1,
    per_page: int = 20,
):
    _ensure_comunicados_table(db)
    is_admin = user.get("is_admin") or False
    where_clauses = []
    params = []
    if filtro == "rascunhos":
        if not is_admin and not _can_publish_comunicado(user):
            raise HTTPException(status_code=403, detail="Sem permissão.")
        where_clauses.append("c.author_key = %s AND c.is_draft = 1 AND c.is_deleted = 0")
        params.append(user["key"])
    elif filtro == "lixeira":
        if not is_admin:
            raise HTTPException(status_code=403, detail="Sem permissão.")
        where_clauses.append("c.is_deleted = 1")
    else:
        where_clauses.append("c.is_deleted = 0 AND c.is_published = 1")
        if not is_admin:
            where_clauses.append("(c.target_audience = 'all' OR c.author_key = %s)")
            params.append(user["key"])
    offset = (page - 1) * per_page
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    rows = db.execute(
        f"SELECT c.* FROM communications c WHERE {where_sql} ORDER BY c.created_at DESC LIMIT %s OFFSET %s",
        (*params, per_page, offset)
    ).fetchall()
    total_row = db.execute(
        f"SELECT COUNT(*) as cnt FROM communications c WHERE {where_sql}", params
    ).fetchone()
    total = total_row["cnt"] if total_row else 0
    # Check read status for each
    read_ids = set()
    read_rows = db.execute(
        "SELECT cr.communication_id FROM communication_reads cr WHERE cr.user_key = %s",
        (user["key"],)
    ).fetchall()
    for r in read_rows:
        read_ids.add(r["communication_id"])
    result = []
    for row in rows:
        d = _comunicado_to_list_dict(row)
        d["is_read"] = row["id"] in read_ids
        result.append(d)
    return {"comunicados": result, "total": total, "page": page, "per_page": per_page}


# ── UNREAD COUNT for bell ─────────────────────────────────────────────────────
@app.get("/api/comunicados/unread/count")
def comunicados_nao_lidos_count(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    row = db.execute(
        """SELECT COUNT(*) as cnt FROM communications c
           WHERE c.is_published = 1 AND c.is_deleted = 0
           AND c.id NOT IN (
               SELECT cr.communication_id FROM communication_reads cr WHERE cr.user_key = %s
           )
           AND (c.target_audience = 'all' OR c.author_key = %s)""",
        (user["key"], user["key"])
    ).fetchone()
    return {"count": row["cnt"] if row else 0}


# ── COMUNICADOS STATS ─────────────────────────────────────────────────────────
@app.get("/api/comunicados/stats")
def comunicados_stats(user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    total = db.execute(
        "SELECT COUNT(*) as cnt FROM communications WHERE is_deleted=0"
    ).fetchone()["cnt"]
    published = db.execute(
        "SELECT COUNT(*) as cnt FROM communications WHERE is_published=1 AND is_deleted=0"
    ).fetchone()["cnt"]
    drafts = db.execute(
        "SELECT COUNT(*) as cnt FROM communications WHERE is_draft=1 AND is_deleted=0 AND author_key=%s",
        (user["key"],)
    ).fetchone()["cnt"]
    return {"total": total, "published": published, "drafts": drafts}


# ── GET single comunicado ────────────────────────────────────────────────────
@app.get("/api/comunicados/{comm_id}")
def get_comunicado(comm_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    if row["is_deleted"]:
        if not user.get("is_admin"):
            raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    if not row["is_published"] and row["author_key"] != user["key"] and not user.get("is_admin"):
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    d = _comunicado_to_dict(row)
    # Increment views count
    db.execute("UPDATE communications SET views_count = views_count + 1 WHERE id=%s", (comm_id,))
    d["views_count"] = (d.get("views_count") or 0) + 1
    db.commit()
    return d


# ── UPDATE comunicado ─────────────────────────────────────────────────────────
@app.put("/api/comunicados/{comm_id}")
def atualizar_comunicado(comm_id: str, body: AtualizarComunicadoRequest, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    if row["author_key"] != user["key"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Sem permissão para editar este comunicado.")
    if row["is_published"]:
        raise HTTPException(status_code=400, detail="Comunicado já publicado. Não pode ser editado.")
    now = datetime.datetime.utcnow().isoformat()
    updates = []
    params = []
    if body.title is not None:
        safe_title = _sanitize_text(body.title.strip())[:200]
        if not safe_title:
            raise HTTPException(status_code=400, detail="Título não pode ser vazio.")
        updates.append("title = %s")
        params.append(safe_title)
    if body.content is not None:
        if len(body.content) > 150000:
            raise HTTPException(status_code=400, detail="Conteúdo excede o limite de 150KB.")
        safe_content = _sanitize_html(body.content)
        updates.append("content = %s")
        params.append(safe_content if safe_content.strip() else body.content[:150000])
    if body.target_audience is not None:
        if body.target_audience not in ("all", "rh", "leader", "admin", "diretor", "platina", "dourado", "diamante"):
            raise HTTPException(status_code=400, detail="Audiência inválida.")
        updates.append("target_audience = %s")
        params.append(body.target_audience)
    if body.priority is not None:
        if body.priority not in ("normal", "urgent"):
            raise HTTPException(status_code=400, detail="Prioridade inválida.")
        updates.append("priority = %s")
        params.append(body.priority)
    if body.is_draft is not None:
        updates.append("is_draft = %s")
        params.append(1 if body.is_draft else 0)
    if not updates:
        return {"ok": True}
    updates.append("updated_at = %s")
    params.append(now)
    params.append(comm_id)
    db.execute(f"UPDATE communications SET {', '.join(updates)} WHERE id=%s", params)
    db.commit()
    return {"ok": True}


# ── PUBLISH comunicado ────────────────────────────────────────────────────────
@app.post("/api/comunicados/{comm_id}/publish")
def publicar_comunicado(comm_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    if row["is_published"]:
        raise HTTPException(status_code=400, detail="Comunicado já publicado.")
    if row["is_deleted"]:
        raise HTTPException(status_code=400, detail="Comunicado está na lixeira.")
    if row["author_key"] != user["key"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Sem permissão para publicar este comunicado.")
    _check_comunicado_rate_limit(user["key"])
    now = datetime.datetime.utcnow().isoformat()
    db.execute("""
        UPDATE communications
        SET is_draft = 0, is_published = 1, published_at = %s, updated_at = %s
        WHERE id = %s
    """, (now, now, comm_id))
    # Re-read to get the updated row with author info
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    safe_title = _sanitize_text(row["title"])
    # Send notification to all users
    notif_title = "📢 Novo comunicado"
    notif_msg = f"{user['name']} publicou: {safe_title[:100]}"
    _notify(db, title=notif_title, message=notif_msg,
            ntype="comunicado",
            audience=row["target_audience"] if row["target_audience"] not in ("all", "") else "all",
            sender_key=user["key"], sender_name=user["name"],
            reference_id=comm_id, play_sound=False)
    # Track notification sent
    notif_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO communication_notifications (id, communication_id, notified_at, total_recipients) VALUES (%s,%s,%s,%s)",
        (notif_id, comm_id, now, 0)
    )
    _log_atividade(db, "comunicado", user["key"], f"Publicou comunicado: {safe_title[:100]}")
    # Emit WebSocket for real-time
    ws_emit("comunicado_published", _comunicado_to_dict(row), rooms=["all"])
    db.commit()
    return {"ok": True, "id": comm_id}


# ── SOFT DELETE comunicado ────────────────────────────────────────────────────
@app.delete("/api/comunicados/{comm_id}")
def deletar_comunicado(comm_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    if row["author_key"] != user["key"] and not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Sem permissão para excluir este comunicado.")
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE communications SET is_deleted = 1, deleted_at = %s, deleted_by_key = %s, updated_at = %s WHERE id=%s",
        (now, user["key"], now, comm_id)
    )
    safe_title = _sanitize_text(row["title"])
    _log_atividade(db, "comunicado", user["key"], f"Excluiu comunicado: {safe_title[:100]}")
    db.commit()
    return {"ok": True}


# ── MARK AS READ ──────────────────────────────────────────────────────────────
@app.post("/api/comunicados/{comm_id}/read")
def marcar_comunicado_lido(comm_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    if not row or row["is_deleted"]:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    now = datetime.datetime.utcnow().isoformat()
    existing = db.execute(
        "SELECT * FROM communication_reads WHERE communication_id=%s AND user_key=%s",
        (comm_id, user["key"])
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE communication_reads SET read_count = read_count + 1, read_at = %s WHERE id=%s",
            (now, existing["id"])
        )
    else:
        read_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO communication_reads (id, communication_id, user_key, read_at, read_count) VALUES (%s,%s,%s,%s,1)",
            (read_id, comm_id, user["key"], now)
        )
    db.commit()
    return {"ok": True}


# ── LIST READERS (audit) ──────────────────────────────────────────────────────
@app.get("/api/comunicados/{comm_id}/readers")
def listar_leitura_comunicado(comm_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    _ensure_comunicados_table(db)
    is_admin = user.get("is_admin") or False
    is_rh = user.get("is_rh") or False
    is_diretor = user.get("is_diretor") or False
    if not (is_admin or is_rh or is_diretor):
        raise HTTPException(status_code=403, detail="Sem permissão para ver relatório de leitura.")
    row = db.execute("SELECT * FROM communications WHERE id=%s", (comm_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Comunicado não encontrado.")
    readers = db.execute(
        """SELECT cr.user_key, u.name, u.initials, u.color, u.photo_url,
                  cr.read_at, cr.read_count
           FROM communication_reads cr
           JOIN users u ON u.key = cr.user_key
           WHERE cr.communication_id = %s
           ORDER BY cr.read_at DESC""",
        (comm_id,)
    ).fetchall()
    total_users = db.execute("SELECT COUNT(*) as cnt FROM users").fetchone()["cnt"]
    read_count = len(readers)
    return {
        "readers": [dict(r) for r in readers],
        "total_readers": read_count,
        "total_users": total_users,
        "read_percentage": round((read_count / total_users * 100), 1) if total_users > 0 else 0,
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
    _auto_concluir_feedback(db, user)

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
    ws_emit("user_online", {"user_key": user["key"], "last_activity": now})
    return {"ok": True}

@app.post("/api/presence/logout")
def presence_logout(user=Depends(get_current_user), db=Depends(get_db)):
    now = datetime.datetime.utcnow().isoformat()
    db.execute("UPDATE presence SET is_online=0, last_seen=%s WHERE user_key=%s", (now, user["key"]))
    db.commit()
    ws_emit("user_offline", {"user_key": user["key"], "last_seen": now})
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
    if is_ouvidor or user.get("is_admin") or user.get("is_admin_user"):
        rows = db.execute("SELECT * FROM ouvidoria ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM ouvidoria WHERE author_key=%s ORDER BY created_at DESC",
            (user["key"],)
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        if isinstance(item.get("responses"), str):
            item["responses"] = json.loads(item["responses"])
        if user.get("is_admin") or user.get("is_admin_user"):
            item["author_name"] = "Anônimo"
        elif is_ouvidor and item.get("anonymous"):
            item["author_name"] = "Anônimo"
        result.append(item)
    return result

@app.post("/api/ouvidoria")
def create_ouvidoria(body: OuvidoriaRequest, user=Depends(get_current_user), db=Depends(get_db)):
    oid = str(uuid.uuid4())
    display_name = body.author_display_name or user["name"]
    db.execute(
        "INSERT INTO ouvidoria (id, author_key, author_name, category, text, status, anonymous, created_at) VALUES (%s,%s,%s,%s,%s,'aberta',%s,%s)",
        (oid, user["key"], display_name, body.category, body.text,
         int(body.anonymous), datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    ws_emit("ouvidoria_updated", {"type": "created", "id": oid, "user_key": user["key"]})
    return {"ok": True, "id": oid}

@app.put("/api/ouvidoria/{oid}/status")
def update_ouvidoria_status(oid: str, body: OuvidoriaStatusRequest, user=Depends(get_current_user), db=Depends(get_db)):
    require_ouvidor(user)
    db.execute("UPDATE ouvidoria SET status=%s WHERE id=%s", (body.status, oid))
    log_audit(db, user["key"], "ouvidoria_status", None, f"Status alterado para {body.status}")
    db.commit()
    return {"ok": True}

@app.delete("/api/ouvidoria/{oid}")
def delete_ouvidoria(oid: str, user=Depends(get_current_user), db=Depends(get_db)):
    require_ouvidor(user)
    db.execute("DELETE FROM ouvidoria WHERE id=%s", (oid,))
    db.commit()
    return {"ok": True}

@app.post("/api/ouvidoria/{oid}/respond")
def respond_ouvidoria(oid: str, body: OuvidoriaResponseRequest, user=Depends(get_current_user), db=Depends(get_db)):
    is_ouvidor = user.get("is_ouvidor") or (user.get("role") or "").lower() == "ouvidor"
    row = db.execute("SELECT * FROM ouvidoria WHERE id=%s", (oid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ouvidoria não encontrada")
    is_owner = row["author_key"] == user["key"]
    if not is_ouvidor and not user.get("is_admin") and not user.get("is_admin_user") and not is_owner:
        raise HTTPException(status_code=403, detail="Sem permissão para responder.")
    responses = json.loads(row["responses"] or "[]")
    responses.append({
        "author_key": user["key"],
        "author_name": user["name"],
        "is_ouvidor": is_ouvidor,
        "text": body.text,
        "created_at": datetime.datetime.utcnow().isoformat()
    })
    db.execute("UPDATE ouvidoria SET responses=%s WHERE id=%s", (json.dumps(responses), oid))
    # Notify the other party
    other_key = row["author_key"]
    if other_key == user["key"]:
        other_key = None
    if other_key:
        _notify(db, title="📬 Ouvidoria respondida",
                message=f"{user['name']} respondeu sua manifestação",
                ntype="system", target_user_key=other_key,
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
    _invalidate_user_cache(target_key)
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

    _auto_concluir_humor(db, user)

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
    activity_id = str(uuid.uuid4())
    created_at = datetime.datetime.utcnow().isoformat()
    db.execute(
        """INSERT INTO atividades_dialogos (id, tipo, autor_key, target_key, target_nome, descricao, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (activity_id, tipo, autor_key, target_key, target_nome, descricao, created_at)
    )
    with get_db_context() as db2:
        user_row = db2.execute("SELECT name, initials, photo_url FROM users WHERE key=%s", (autor_key,)).fetchone()
    payload = {
        "id": activity_id,
        "tipo": _sanitize_text(tipo)[:30],
        "descricao": _sanitize_text(descricao)[:400],
        "created_at": created_at,
        "autor_key": autor_key,
        "autor_nome": user_row["name"] if user_row else "",
        "autor_initials": user_row["initials"] if user_row else "",
        "autor_photo": user_row["photo_url"] if user_row else "",
    }
    ws_emit("new_activity", payload)

def _normalize_atividade_row(row: dict):
    # Security: response allowlist + sanitization mitigates XSS/injection in UI.
    # Only fields explicitly needed by the feed are exposed to the frontend.
    return {
        "id": row.get("id"),
        "tipo": _sanitize_text((row.get("tipo") or ""))[:30],
        "descricao": _sanitize_text((row.get("descricao") or ""))[:400],
        "created_at": row.get("created_at"),
        "autor_key": _sanitize_text((row.get("autor_key") or ""))[:80],
        "autor_nome": _sanitize_text((row.get("autor_nome") or ""))[:80],
        "autor_initials": _sanitize_text((row.get("autor_initials") or ""))[:8],
        "autor_photo": row.get("autor_photo"),
    }


@app.get("/api/atividades")
def listar_atividades(limit: int = 50, user=Depends(get_current_user), db=Depends(get_db)):
    # Security: authentication is enforced by JWT dependency (get_current_user).
    # Client-side role/user data is never trusted here.
    _check_activity_rate_limit(user["key"])

    # Security: clamp query parameter to prevent forced over-fetch / endpoint abuse.
    requested_limit = int(limit) if isinstance(limit, int) else 50
    safe_limit = max(1, min(requested_limit, 100))
    if safe_limit != requested_limit:
        logger.warning("activity_limit_clamped user=%s requested=%s safe=%s", user["key"], requested_limit, safe_limit)

    rows = db.execute(
        """SELECT a.id, a.tipo, a.descricao, a.created_at, a.autor_key,
                  u.name AS autor_nome, u.initials AS autor_initials, u.photo_url AS autor_photo
           FROM atividades_dialogos a
           LEFT JOIN users u ON u.key = a.autor_key
           ORDER BY a.created_at DESC LIMIT %s""",
        (safe_limit,)
    ).fetchall()
    return [_normalize_atividade_row(dict(r)) for r in rows]


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
    if target_key == "@todos":
        _notify(db, title="🎉 Celebração",
                message=f"{user['name']} celebrou @todos — {mensagem[:80]}" if mensagem else f"{user['name']} celebrou @todos",
                ntype="celebration", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                play_sound=False)
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
        (id, doctor_id, name, value_cash, value_card_pix, value_bradesco, position_order, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (proc_id, body.doctor_id, body.name, body.value_cash or 0, body.value_card_pix or 0,
        body.value_bradesco or 0,
        body.position_order, datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": proc_id}

@app.put("/api/price-procedures/{proc_id}")
def update_price_procedure(proc_id: str, body: PriceProcedureRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    db.execute("""UPDATE price_procedures SET name=%s, value_cash=%s, value_card_pix=%s, value_bradesco=%s,
        position_order=%s WHERE id=%s""",
        (body.name, body.value_cash or 0, body.value_card_pix or 0, body.value_bradesco or 0,
        body.position_order, proc_id)
    )
    db.commit()
    return {"ok": True}

@app.delete("/api/price-procedures/{proc_id}")
def delete_price_procedure(proc_id: str, user=Depends(require_level(1)), db=Depends(get_db)):
    db.execute("DELETE FROM price_procedures WHERE id=%s", (proc_id,))
    db.commit()
    return {"ok": True}

@app.get("/api/price-export/{folder_id}")
def export_price_table(folder_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    doctors = db.execute("SELECT * FROM price_doctors WHERE folder_id=%s ORDER BY position_order ASC",
                         (folder_id,)).fetchall()
    doctor_ids = [d["id"] for d in doctors]
    if doctor_ids:
        placeholders = ",".join("%s" for _ in doctor_ids)
        procs = db.execute(f"SELECT * FROM price_procedures WHERE doctor_id IN ({placeholders}) ORDER BY position_order ASC",
                           doctor_ids).fetchall()
    else:
        procs = []
    procs_by_doctor = {}
    for p in procs:
        procs_by_doctor.setdefault(p["doctor_id"], []).append(dict(p))
    result = []
    for d in doctors:
        row = dict(d)
        row["procedures"] = procs_by_doctor.get(d["id"], [])
        result.append(row)
    return result

# ── POPS (Procedimento Operacional Padrão) ─────────────────────────────────────

ALLOWED_POP_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".xml", ".json", ".mp4", ".mp3"}
MAX_POP_FILE_SIZE = 3 * 1024 * 1024  # 3MB

@app.get("/api/pops-modules")
def list_pop_modules(folder_id: str = Query(...), user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM pop_modules WHERE folder_id=%s ORDER BY position_order ASC", (folder_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/pops-modules")
def create_pop_module(body: POPModuleRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    module_id = str(uuid.uuid4())
    db.execute("""INSERT INTO pop_modules (id, folder_id, name, icon, position_order, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (module_id, body.folder_id, body.name, body.icon, body.position_order or 0,
         datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": module_id}

@app.put("/api/pops-modules/{module_id}")
def update_pop_module(module_id: str, body: POPModuleRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    existing = db.execute("SELECT * FROM pop_modules WHERE id=%s", (module_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Módulo não encontrado")
    db.execute("UPDATE pop_modules SET name=%s, icon=%s, position_order=%s WHERE id=%s",
        (body.name, body.icon, body.position_order or 0, module_id))
    db.commit()
    return {"ok": True}

@app.delete("/api/pops-modules/{module_id}")
def delete_pop_module(module_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    existing = db.execute("SELECT * FROM pop_modules WHERE id=%s", (module_id,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Módulo não encontrado")
    db.execute("DELETE FROM pop_files WHERE module_id=%s", (module_id,))
    db.execute("DELETE FROM pop_modules WHERE id=%s", (module_id,))
    db.commit()
    return {"ok": True}

@app.get("/api/pops-modules/{module_id}/files")
def list_pop_files(module_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM pop_files WHERE module_id=%s ORDER BY created_at DESC", (module_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/pops-modules/{module_id}/files")
def upload_pop_file(
    module_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    module = db.execute("SELECT * FROM pop_modules WHERE id=%s", (module_id,)).fetchone()
    if not module:
        raise HTTPException(status_code=404, detail="Módulo não encontrado")
    _check_upload_rate_limit(user["key"])

    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome")

    ext = Path(file.filename).suffix.lower()
    if _is_executable(ext):
        raise HTTPException(status_code=400, detail="Arquivos executáveis não são permitidos")
    if ext not in ALLOWED_POP_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extensão {ext} não permitida para POPs")

    if file.size and file.size > MAX_POP_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Arquivo muito grande (máx 3MB)")

    try:
        unique_name = f"{uuid.uuid4()}{ext}"
        result = cloudinary.uploader.upload(
            file.file,
            folder="dialogos/pops",
            public_id=unique_name.replace(ext, ""),
            resource_type="auto"
        )
        url = result["secure_url"]
        file_id = str(uuid.uuid4())
        db.execute("""INSERT INTO pop_files (id, module_id, name, url, size, mime_type, uploaded_by, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (file_id, module_id, file.filename, url,
             file.size or 0, file.content_type or "",
             user["name"], datetime.datetime.utcnow().isoformat())
        )
        _notify(db, title="📄 POP enviado",
                message=f"{user['name']} enviou {file.filename} para {module['name']}",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=file_id, play_sound=False)
        db.commit()
        return {"ok": True, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/pops-files/{file_id}")
def delete_pop_file(file_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    f = db.execute("SELECT * FROM pop_files WHERE id=%s", (file_id,)).fetchone()
    if not f:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if f["uploaded_by"] != user["name"] and user["access_level"] < 2:
        raise HTTPException(status_code=403, detail="Você só pode remover seus próprios arquivos")
    db.execute("DELETE FROM pop_files WHERE id=%s", (file_id,))
    db.commit()
    return {"ok": True}

@app.post("/api/pops-files/{file_id}/replace")
def replace_pop_file(
    file_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    f = db.execute("SELECT * FROM pop_files WHERE id=%s", (file_id,)).fetchone()
    if not f:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if f["uploaded_by"] != user["name"] and user["access_level"] < 2:
        raise HTTPException(status_code=403, detail="Você só pode substituir seus próprios arquivos")
    _check_upload_rate_limit(user["key"])

    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome")
    ext = Path(file.filename).suffix.lower()
    if _is_executable(ext):
        raise HTTPException(status_code=400, detail="Arquivos executáveis não são permitidos")
    if ext not in ALLOWED_POP_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extensão {ext} não permitida para POPs")
    if file.size and file.size > MAX_POP_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Arquivo muito grande (máx 3MB)")

    try:
        unique_name = f"{uuid.uuid4()}{ext}"
        result = cloudinary.uploader.upload(
            file.file,
            folder="dialogos/pops",
            public_id=unique_name.replace(ext, ""),
            resource_type="auto"
        )
        url = result["secure_url"]
        db.execute("""UPDATE pop_files SET name=%s, url=%s, size=%s, mime_type=%s, uploaded_by=%s, created_at=%s WHERE id=%s""",
            (file.filename, url, file.size or 0, file.content_type or "",
             user["name"], datetime.datetime.utcnow().isoformat(), file_id)
        )
        _notify(db, title="📄 POP substituído",
                message=f"{user['name']} substituiu {file.filename} em POPs",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=file_id, play_sound=False)
        db.commit()
        return {"ok": True, "url": url, "id": file_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/pops-files/{file_id}/content")
def update_pop_file_content(file_id: str, body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    f = db.execute("SELECT * FROM pop_files WHERE id=%s", (file_id,)).fetchone()
    if not f:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if f["uploaded_by"] != user["name"] and user["access_level"] < 2:
        raise HTTPException(status_code=403, detail="Você só pode editar seus próprios arquivos")

    content = body.get("content", "")
    ext = Path(f["name"]).suffix.lower()
    if ext not in {".txt", ".csv", ".xml", ".json", ".md", ".log", ".yml", ".yaml", ".ini", ".cfg", ".env", ".bat"}:
        raise HTTPException(status_code=400, detail="Este tipo de arquivo não pode ser editado como texto")

    try:
        import io
        content_bytes = content.encode("utf-8")
        file_like = io.BytesIO(content_bytes)

        unique_name = f"{uuid.uuid4()}{ext}"
        result = cloudinary.uploader.upload(
            file_like,
            folder="dialogos/pops",
            public_id=unique_name.replace(ext, ""),
            resource_type="raw"
        )
        url = result["secure_url"]
        db.execute("""UPDATE pop_files SET url=%s, size=%s, mime_type=%s, uploaded_by=%s, created_at=%s WHERE id=%s""",
            (url, len(content_bytes), "text/plain",
             user["name"], datetime.datetime.utcnow().isoformat(), file_id)
        )
        db.commit()
        return {"ok": True, "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/api/gamificacao/leaderboard-months")
def get_leaderboard_months(user=Depends(get_current_user), db=Depends(get_db)):
    """Listar meses com ranking disponível"""
    rows = db.execute("""
        SELECT DISTINCT month FROM monthly_ranking
        ORDER BY month DESC
    """).fetchall()
    months = [dict(r)["month"] for r in rows]
    return months

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

# ── OBJETIVOS GAMIFICADOS (CRUD + PROGRESSO) ──────────────────────────────

@app.get("/api/objetivos")
def listar_objetivos(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM objetivos_def ORDER BY created_at DESC").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        prog = db.execute(
            "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
            (d["id"], user["key"])
        ).fetchone()
        d["user_progress"] = dict(prog) if prog else None
        result.append(d)
    return result

@app.post("/api/objetivos")
def criar_objetivo(body: dict = None, user=Depends(get_current_user), db=Depends(get_db)):
    if not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem criar objetivos.")
    oid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    nome = (body or {}).get("nome", "").strip()
    if not nome:
        raise HTTPException(status_code=422, detail="Nome é obrigatório.")
    db.execute(
        """INSERT INTO objetivos_def (id, nome, descricao, categoria, recompensa_dcoins,
           meta_valor, meta_unidade, periodicidade, tipo_progresso, icone, ativo, owner_key, created_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (oid, nome, (body or {}).get("descricao", ""),
         (body or {}).get("categoria", "tarefas"),
         (body or {}).get("recompensa_dcoins", 10),
         (body or {}).get("meta_valor", 1),
         (body or {}).get("meta_unidade", "tarefas"),
         (body or {}).get("periodicidade", "diaria"),
         (body or {}).get("tipo_progresso", "incremental"),
         (body or {}).get("icone", "ti-star"),
         1 if (body or {}).get("ativo", True) else 0,
         user["key"], now)
    )
    db.commit()
    return {"ok": True, "id": oid}

@app.put("/api/objetivos/{oid}")
def atualizar_objetivo(oid: str, body: dict = None, user=Depends(get_current_user), db=Depends(get_db)):
    if not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem editar objetivos.")
    existing = db.execute("SELECT * FROM objetivos_def WHERE id=%s", (oid,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Objetivo não encontrado.")
    b = body or {}
    updates = []
    params = []
    for col in ("nome", "descricao", "categoria", "recompensa_dcoins", "meta_valor",
                "meta_unidade", "periodicidade", "tipo_progresso", "icone"):
        if col in b:
            updates.append(f"{col}=%s")
            params.append(b[col])
    if "ativo" in b:
        updates.append("ativo=%s")
        params.append(1 if b["ativo"] else 0)
    if updates:
        params.append(oid)
        db.execute(f"UPDATE objetivos_def SET {', '.join(updates)} WHERE id=%s", params)
        # Se foi desbloqueado (0→1), resetar progresso para zero
        if b.get("ativo") and not existing.get("ativo"):
            db.execute(
                "UPDATE objetivos_progress SET progresso_atual=0, status='pendente', ultima_atualizacao=%s WHERE objetivo_id=%s",
                (datetime.datetime.utcnow().isoformat(), oid)
            )
        db.commit()
        ws_emit("objective_updated", {"type": "updated", "id": oid, "user_key": user["key"]})
    return {"ok": True}

@app.delete("/api/objetivos/{oid}")
def deletar_objetivo(oid: str, user=Depends(get_current_user), db=Depends(get_db)):
    if not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Apenas administradores podem remover objetivos.")
    db.execute("DELETE FROM objetivos_progress WHERE objetivo_id=%s", (oid,))
    db.execute("DELETE FROM objetivos_def WHERE id=%s", (oid,))
    db.commit()
    ws_emit("objective_updated", {"type": "deleted", "id": oid, "user_key": user["key"]})
    return {"ok": True}

def _check_objective_rate_limit(user_key: str):
    now = time.time()
    minute = int(now / 15)
    key = f"obj:{user_key}:{minute}"
    count = _objective_limits.get(key, 0)
    if count >= 5:
        raise HTTPException(status_code=429, detail="Limite de ações em objetivos excedido. Aguarde alguns segundos.")
    _objective_limits[key] = count + 1

def _log_objective_audit(db, objetivo_id, user_key, action, detail=""):
    request = getattr(_log_objective_audit, "_request", None)
    ip = ""
    if request:
        ip = request.client.host if hasattr(request, "client") and request.client else ""
    db.execute(
        "INSERT INTO objetivos_audit_log (id, objetivo_id, user_key, action, detail, ip_address, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), objetivo_id, user_key, action, detail, ip, datetime.datetime.utcnow().isoformat())
    )

def _update_streak(db, user_key):
    hoje = datetime.datetime.utcnow().date().isoformat()
    streak = db.execute("SELECT * FROM objetivos_streaks WHERE user_key=%s", (user_key,)).fetchone()
    if streak:
        if streak["last_date"] == hoje:
            return streak["current_streak"]
        yesterday = (datetime.datetime.utcnow().date() - datetime.timedelta(days=1)).isoformat()
        if streak["last_date"] == yesterday:
            novo = streak["current_streak"] + 1
        else:
            novo = 1
        novo_max = max(novo, streak["max_streak"])
        db.execute(
            "UPDATE objetivos_streaks SET current_streak=%s, max_streak=%s, last_date=%s, updated_at=%s WHERE user_key=%s",
            (novo, novo_max, hoje, datetime.datetime.utcnow().isoformat(), user_key)
        )
        return novo
    else:
        sid = str(uuid.uuid4())
        now = datetime.datetime.utcnow().isoformat()
        db.execute(
            "INSERT INTO objetivos_streaks (id, user_key, current_streak, max_streak, last_date, updated_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (sid, user_key, 1, 1, hoje, now)
        )
        return 1

# ── Auto-concluir "Faça Login" no login ─────────────────────────────────────
def _update_login_streak(db, user_key):
    hoje = datetime.datetime.utcnow().date()
    hoje_str = hoje.isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    streak = db.execute("SELECT * FROM objetivos_streaks WHERE user_key=%s", (user_key,)).fetchone()
    if streak:
        if streak["last_date"] == hoje_str:
            return streak["current_streak"]
        last = datetime.date.fromisoformat(streak["last_date"])
        delta = (hoje - last).days
        only_weekends = True
        for i in range(1, delta):
            d = last + datetime.timedelta(days=i)
            if d.weekday() < 5:
                only_weekends = False
                break
        if delta == 1 or (delta > 1 and only_weekends):
            novo = streak["current_streak"] + 1
        else:
            novo = 1
        novo_max = max(novo, streak["max_streak"])
        db.execute(
            "UPDATE objetivos_streaks SET current_streak=%s, max_streak=%s, last_date=%s, updated_at=%s WHERE user_key=%s",
            (novo, novo_max, hoje_str, agora, user_key)
        )
        return novo
    sid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO objetivos_streaks (id, user_key, current_streak, max_streak, last_date, updated_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (sid, user_key, 1, 1, hoje_str, agora)
    )
    return 1

def _auto_progress_tarefas(db, user_key):
    hoje = datetime.datetime.utcnow().date().isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    objetivos = db.execute(
        "SELECT * FROM objetivos_def WHERE categoria='tarefas' AND ativo=1"
    ).fetchall()
    for obj in objetivos:
        prog = db.execute(
            "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
            (obj["id"], user_key)
        ).fetchone()

        if prog and prog["status"] == "concluido":
            continue

        if prog:
            novo = (prog["progresso_atual"] or 0) + 1
            status = "concluido" if novo >= obj["meta_valor"] else "progresso"
            db.execute(
                "UPDATE objetivos_progress SET progresso_atual=%s, status=%s, ultima_atualizacao=%s WHERE id=%s",
                (novo, status, agora, prog["id"])
            )
        else:
            pid = str(uuid.uuid4())
            novo = 1
            status = "concluido" if novo >= obj["meta_valor"] else "progresso"
            db.execute(
                "INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (pid, obj["id"], user_key, novo, status, hoje, agora, agora)
            )

        if status == "concluido":
            _award_dcoins(db, user_key, obj["recompensa_dcoins"], f"Objetivo concluído: {obj['nome']}")
            _update_streak(db, user_key)

        ev = "objective_completed" if status == "concluido" else "objective_updated"
        ws_emit_to_user(user_key, ev, {"id": obj["id"], "user_key": user_key, "status": status, "progresso": novo, "nome": obj["nome"]})

def _auto_concluir_feedback(db, user):
    hoje = datetime.datetime.utcnow().date().isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    uk = user["key"]
    obj = db.execute(
        "SELECT * FROM objetivos_def WHERE nome ILIKE %s AND ativo=1",
        ("%feedback%",)
    ).fetchone()
    if not obj:
        return False
    prog = db.execute(
        "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
        (obj["id"], uk)
    ).fetchone()
    if prog and prog["status"] == "concluido" and prog["ultima_atualizacao"][:10] == hoje:
        return False
    if prog:
        db.execute(
            "UPDATE objetivos_progress SET progresso_atual=%s, status='concluido', ultima_atualizacao=%s WHERE id=%s",
            (obj["meta_valor"], agora, prog["id"])
        )
    else:
        pid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, obj["id"], uk, obj["meta_valor"], "concluido", hoje, agora, agora)
        )
    _award_dcoins(db, uk, obj["recompensa_dcoins"], f"Feedback dado: {obj['nome']}", notify=False)
    _log_atividade(db, "objetivo", user["key"], f"{user['name']} concluiu um Objetivo!")
    ws_emit_to_user(uk, "objective_completed",
                    {"id": obj["id"], "user_key": uk, "status": "concluido", "progresso": obj["meta_valor"], "nome": obj["nome"]})
    return obj["nome"]

def _auto_concluir_humor(db, user):
    hoje = datetime.datetime.utcnow().date().isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    uk = user["key"]
    obj = db.execute(
        "SELECT * FROM objetivos_def WHERE nome ILIKE %s AND ativo=1",
        ("%humor%",)
    ).fetchone()
    if not obj:
        return False
    prog = db.execute(
        "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
        (obj["id"], uk)
    ).fetchone()
    if prog and prog["status"] == "concluido" and prog["ultima_atualizacao"][:10] == hoje:
        return False
    if prog:
        db.execute(
            "UPDATE objetivos_progress SET progresso_atual=%s, status='concluido', ultima_atualizacao=%s WHERE id=%s",
            (obj["meta_valor"], agora, prog["id"])
        )
    else:
        pid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, obj["id"], uk, obj["meta_valor"], "concluido", hoje, agora, agora)
        )
    _award_dcoins(db, uk, obj["recompensa_dcoins"], f"Humor registrado: {obj['nome']}", notify=False)
    _log_atividade(db, "objetivo", user["key"], f"{user['name']} concluiu um Objetivo!")
    db.commit()
    ws_emit_to_user(uk, "objective_completed",
                    {"id": obj["id"], "user_key": uk, "status": "concluido", "progresso": obj["meta_valor"], "nome": obj["nome"]})
    return obj["nome"]

def _auto_concluir_login(db, user):
    hoje = datetime.datetime.utcnow().date()
    dia_semana = hoje.weekday()
    if dia_semana >= 5:
        return False
    # ILIKE = case-insensitive (PostgreSQL); funciona com acentos (faça, ç, ã)
    obj = db.execute("SELECT * FROM objetivos_def WHERE nome ILIKE %s AND ativo=1", ("%faça%login%",)).fetchone()
    if not obj:
        return False
    hoje_str = hoje.isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    uk = user["key"]

    prog = db.execute("SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s", (obj["id"], uk)).fetchone()

    # One-time migration: if progress exists but ultimo_reset is NULL (manual/old style), wipe and restart fresh
    if prog and prog.get("ultimo_reset") is None:
        db.execute("DELETE FROM objetivos_progress WHERE id=%s", (prog["id"],))
        db.execute("DELETE FROM user_points WHERE user_key=%s AND reason LIKE %s", (uk, "%Login%"))
        prog = None

    if prog and prog["status"] == "concluido" and prog["ultima_atualizacao"][:10] == hoje_str:
        return False

    if prog:
        db.execute("UPDATE objetivos_progress SET progresso_atual=%s, status='concluido', ultima_atualizacao=%s WHERE id=%s",
                    (obj["meta_valor"], agora, prog["id"]))
    else:
        pid = str(uuid.uuid4())
        db.execute("INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (pid, obj["id"], uk, obj["meta_valor"], "concluido", hoje_str, agora, agora))
    _award_dcoins(db, uk, obj["recompensa_dcoins"], f"Login diário: {obj['nome']}", notify=False)
    _update_login_streak(db, uk)
    _log_atividade(db, "objetivo", user["key"], f"{user['name']} concluiu um Objetivo!")
    db.commit()
    ws_emit_to_user(uk, "objective_completed", {"id": obj["id"], "user_key": uk, "status": "concluido", "progresso": obj["meta_valor"], "nome": obj["nome"]})
    return obj["nome"]

@app.post("/api/objetivos/{oid}/progresso")
def atualizar_progresso(oid: str, body: dict = None, user=Depends(get_current_user), db=Depends(get_db), request: Request = None):
    _log_objective_audit._request = request
    _check_objective_rate_limit(user["key"])

    idempotency_key = (body or {}).get("idempotency_key")
    if idempotency_key:
        if idempotency_key in _idempotency_keys:
            return {"ok": True, "idempotent": True}
        _idempotency_keys[idempotency_key] = True

    objetivo = db.execute("SELECT * FROM objetivos_def WHERE id=%s", (oid,)).fetchone()
    if not objetivo:
        raise HTTPException(status_code=404, detail="Objetivo não encontrado.")
    if not objetivo["ativo"]:
        raise HTTPException(status_code=403, detail="Este objetivo está bloqueado.")

    now = datetime.datetime.utcnow().isoformat()
    hoje = datetime.datetime.utcnow().date().isoformat()
    dia_semana = datetime.datetime.utcnow().weekday()
    dia_mes = datetime.datetime.utcnow().day

    prog = db.execute(
        "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
        (oid, user["key"])
    ).fetchone()

    # Validate period for already completed objectives
    if prog and prog["status"] == "concluido":
        if objetivo["periodicidade"] == "diaria":
            if prog["ultima_atualizacao"][:10] == hoje:
                raise HTTPException(status_code=409, detail="Objetivo diário já concluído hoje.")
        elif objetivo["periodicidade"] == "semanal":
            ultima_semana = datetime.datetime.fromisoformat(prog["ultima_atualizacao"]).date().isocalendar()[1]
            if ultima_semana == datetime.datetime.utcnow().date().isocalendar()[1]:
                raise HTTPException(status_code=409, detail="Objetivo semanal já concluído esta semana.")
        elif objetivo["periodicidade"] == "mensal":
            ultima_dt = datetime.datetime.fromisoformat(prog["ultima_atualizacao"]).date()
            if ultima_dt.year == datetime.datetime.utcnow().date().year and ultima_dt.month == datetime.datetime.utcnow().date().month:
                raise HTTPException(status_code=409, detail="Objetivo mensal já concluído este mês.")

    increment = (body or {}).get("incremento", 1)
    if prog:
        novo_progresso = (prog["progresso_atual"] or 0) + increment
        novo_status = "concluido" if novo_progresso >= objetivo["meta_valor"] else "progresso"
        if objetivo["tipo_progresso"] == "unico":
            novo_progresso = objetivo["meta_valor"]
            novo_status = "concluido"
        db.execute(
            "UPDATE objetivos_progress SET progresso_atual=%s, status=%s, ultima_atualizacao=%s WHERE id=%s",
            (novo_progresso, novo_status, now, prog["id"])
        )
    else:
        pid = str(uuid.uuid4())
        novo_progresso = min(increment, objetivo["meta_valor"])
        novo_status = "concluido" if novo_progresso >= objetivo["meta_valor"] else "progresso"
        db.execute(
            """INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (pid, oid, user["key"], novo_progresso, novo_status, now, now, now)
        )

    if novo_status == "concluido":
        _award_dcoins(db, user["key"], objetivo["recompensa_dcoins"],
                      f"Objetivo concluído: {objetivo['nome']}")
        _update_streak(db, user["key"])
        _log_atividade(db, "objetivo", user["key"], f"{user['name']} concluiu um Objetivo!")

    _log_objective_audit(db, oid, user["key"], "progresso",
                         f"Progresso atualizado para {novo_progresso}/{objetivo['meta_valor']} (status: {novo_status})")

    db.commit()
    event_name = "objective_completed" if novo_status == "concluido" else "objective_updated"
    ws_emit_to_user(user["key"], event_name, {"id": oid, "user_key": user["key"], "status": novo_status, "progresso": novo_progresso})
    return {"ok": True, "status": novo_status, "progresso": novo_progresso}

@app.post("/api/objetivos/reset")
def resetar_objetivos(user=Depends(get_current_user), db=Depends(get_db)):
    hoje_dt = datetime.datetime.utcnow().isoformat()
    dia_semana = datetime.datetime.utcnow().weekday()
    dia_mes = datetime.datetime.utcnow().day
    resetados = 0
    afetados = {}
    objetivos = db.execute("SELECT * FROM objetivos_def WHERE ativo=1").fetchall()
    for obj in objetivos:
        deve_resetar = False
        if obj["periodicidade"] == "diaria":
            deve_resetar = True
        elif obj["periodicidade"] == "semanal" and dia_semana == 0:
            deve_resetar = True
        elif obj["periodicidade"] == "mensal" and dia_mes == 1:
            deve_resetar = True
        if deve_resetar:
            prog_rows = db.execute(
                "SELECT id, user_key, status FROM objetivos_progress WHERE objetivo_id=%s",
                (obj["id"],)
            ).fetchall()
            for pr in prog_rows:
                if pr["status"] == "concluido":
                    uk = pr["user_key"]
                    if uk not in afetados:
                        afetados[uk] = []
                    afetados[uk].append(obj["id"])
            cur = db.execute(
                """UPDATE objetivos_progress SET progresso_atual=0,
                   status=CASE WHEN status='concluido' THEN 'pendente' ELSE status END,
                   ultimo_reset=%s
                   WHERE objetivo_id=%s""",
                (hoje_dt, obj["id"])
            )
            resetados += cur.rowcount
    db.commit()
    for uk, oids in afetados.items():
        for oid in oids:
            ws_emit_to_user(uk, "objective_uncompleted", {"id": oid, "user_key": uk})
    ws_emit("objective_updated", {"type": "reset", "resetados": resetados, "user_key": user["key"]})
    return {"ok": True, "resetados": resetados}

def _award_dcoins(db, user_key, coins, reason, notify=True):
    pid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    target = db.execute("SELECT key, points FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        return
    db.execute(
        "INSERT INTO user_points (id, user_key, points, reason, action_type, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (pid, user_key, coins, reason, "objetivo", now)
    )
    new_total = (target["points"] or 0) + coins
    db.execute("UPDATE users SET points=%s WHERE key=%s", (new_total, user_key))
    if notify:
        _notify(db, title="D-Cash recebido",
                message=f"Você ganhou {coins} D-Cash por: {reason}",
                ntype="dcash", target_user_key=user_key,
                sender_key="system", sender_name="Sistema",
                reference_id=pid, play_sound=True)

@app.get("/api/objetivos/stats")
def objetivos_stats(user=Depends(get_current_user), db=Depends(get_db)):
    key = user["key"]
    total = db.execute("SELECT COUNT(*) as cnt FROM objetivos_def WHERE ativo=1").fetchone()["cnt"] or 0
    concluidos = db.execute(
        "SELECT COUNT(*) as cnt FROM objetivos_progress WHERE user_key=%s AND status='concluido'",
        (key,)
    ).fetchone()["cnt"] or 0
    dcoins_row = db.execute(
        "SELECT COALESCE(SUM(points),0) as total FROM user_points WHERE user_key=%s AND action_type='objetivo'",
        (key,)
    ).fetchone()
    dcoins_ganhos = dcoins_row["total"] if dcoins_row else 0
    streak = db.execute("SELECT * FROM objetivos_streaks WHERE user_key=%s", (key,)).fetchone()
    streak_data = dict(streak) if streak else {"current_streak": 0, "max_streak": 0}
    my_ranking = db.execute(
        "SELECT COUNT(*) + 1 as pos FROM users WHERE points > (SELECT COALESCE(points,0) FROM users WHERE key=%s)",
        (key,)
    ).fetchone()["pos"] if db.execute("SELECT points FROM users WHERE key=%s", (key,)).fetchone() else 0
    return {
        "total": total,
        "concluidos": concluidos,
        "dcoins_ganhos": dcoins_ganhos,
        "dcoins_disponiveis": user.get("points", 0),
        "streak": streak_data,
        "rank": my_ranking,
    }

@app.get("/api/objetivos/streak")
def objetivos_streak(user=Depends(get_current_user), db=Depends(get_db)):
    streak = db.execute("SELECT * FROM objetivos_streaks WHERE user_key=%s", (user["key"],)).fetchone()
    return dict(streak) if streak else {"current_streak": 0, "max_streak": 0, "last_date": None}

@app.get("/api/objetivos/leaderboard")
def objetivos_leaderboard(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT
            u.key, u.name, u.dept, u.color, u.photo_url,
            COALESCE(u.points, 0) AS d_cash_total,
            ROW_NUMBER() OVER (ORDER BY u.points DESC) AS position
        FROM users u
        ORDER BY u.points DESC
        LIMIT 10
    """).fetchall()
    top10 = []
    for r in rows:
        d = dict(r)
        name = d.get("name") or ""
        parts = name.strip().split()
        initials = "".join(p[0] for p in parts if p and p[0].isalpha())[:2].upper() or "??"
        top10.append({
            "key": d["key"],
            "name": name,
            "department": d.get("dept") or "",
            "initials": initials,
            "color": d.get("color") or "#2a2a2a",
            "avatar_url": d.get("photo_url") or None,
            "d_cash_total": d["d_cash_total"],
            "position": d["position"],
        })
    my_position = db.execute("""
        SELECT position FROM (
            SELECT key, ROW_NUMBER() OVER (ORDER BY points DESC) AS position
            FROM users
        ) sub WHERE key=%s
    """, (user["key"],)).fetchone()
    return {
        "top10": top10,
        "myPosition": my_position["position"] if my_position else None,
    }

@app.get("/api/objetivos/{oid}/audit")
def objetivo_audit_log(oid: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM objetivos_audit_log WHERE objetivo_id=%s ORDER BY created_at DESC LIMIT 50",
        (oid,)
    ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/objetivos/{oid}/concluir")
def concluir_objetivo(oid: str, body: dict = None, user=Depends(get_current_user), db=Depends(get_db), request: Request = None):
    _log_objective_audit._request = request
    _check_objective_rate_limit(user["key"])

    idempotency_key = (body or {}).get("idempotency_key")
    if idempotency_key:
        if idempotency_key in _idempotency_keys:
            return {"ok": True, "idempotent": True}
        _idempotency_keys[idempotency_key] = True

    objetivo = db.execute("SELECT * FROM objetivos_def WHERE id=%s", (oid,)).fetchone()
    if not objetivo:
        raise HTTPException(status_code=404, detail="Objetivo não encontrado.")
    if not objetivo["ativo"]:
        raise HTTPException(status_code=403, detail="Este objetivo está bloqueado.")

    now = datetime.datetime.utcnow().isoformat()
    prog = db.execute(
        "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
        (oid, user["key"])
    ).fetchone()

    if prog and prog["status"] == "concluido":
        if objetivo["periodicidade"] == "diaria":
            if prog["ultima_atualizacao"][:10] == datetime.datetime.utcnow().date().isoformat():
                raise HTTPException(status_code=409, detail="Objetivo diário já concluído hoje.")
        elif objetivo["periodicidade"] == "semanal":
            ult_semana = datetime.datetime.fromisoformat(prog["ultima_atualizacao"]).date().isocalendar()[1]
            if ult_semana == datetime.datetime.utcnow().date().isocalendar()[1]:
                raise HTTPException(status_code=409, detail="Objetivo semanal já concluído esta semana.")
        elif objetivo["periodicidade"] == "mensal":
            ult_dt = datetime.datetime.fromisoformat(prog["ultima_atualizacao"]).date()
            if ult_dt.year == datetime.datetime.utcnow().date().year and ult_dt.month == datetime.datetime.utcnow().date().month:
                raise HTTPException(status_code=409, detail="Objetivo mensal já concluído este mês.")

    if prog:
        db.execute(
            "UPDATE objetivos_progress SET progresso_atual=%s, status='concluido', ultima_atualizacao=%s WHERE id=%s",
            (objetivo["meta_valor"], now, prog["id"])
        )
    else:
        pid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, oid, user["key"], objetivo["meta_valor"], "concluido", now, now, now)
        )

    _award_dcoins(db, user["key"], objetivo["recompensa_dcoins"], f"Objetivo concluído: {objetivo['nome']}")
    _update_streak(db, user["key"])
    _log_objective_audit(db, oid, user["key"], "concluir",
                         f"Objetivo concluído manualmente. Recompensa: {objetivo['recompensa_dcoins']} D-Cash")
    db.commit()
    ws_emit_to_user(user["key"], "objective_completed",
                    {"id": oid, "user_key": user["key"], "status": "concluido", "progresso": objetivo["meta_valor"], "nome": objetivo["nome"]})
    return {"ok": True}

@app.post("/api/objetivos/{oid}/incrementar")
def incrementar_objetivo(oid: str, body: dict = None, user=Depends(get_current_user), db=Depends(get_db), request: Request = None):
    _log_objective_audit._request = request
    _check_objective_rate_limit(user["key"])

    idempotency_key = (body or {}).get("idempotency_key")
    if idempotency_key:
        if idempotency_key in _idempotency_keys:
            return {"ok": True, "idempotent": True}
        _idempotency_keys[idempotency_key] = True

    objetivo = db.execute("SELECT * FROM objetivos_def WHERE id=%s", (oid,)).fetchone()
    if not objetivo:
        raise HTTPException(status_code=404, detail="Objetivo não encontrado.")
    if not objetivo["ativo"]:
        raise HTTPException(status_code=403, detail="Este objetivo está bloqueado.")

    now = datetime.datetime.utcnow().isoformat()
    prog = db.execute(
        "SELECT * FROM objetivos_progress WHERE objetivo_id=%s AND user_key=%s",
        (oid, user["key"])
    ).fetchone()
    increment = (body or {}).get("incremento", 1)

    if prog:
        if objetivo["tipo_progresso"] == "unico":
            novo_progresso = objetivo["meta_valor"]
            novo_status = "concluido"
        else:
            novo_progresso = (prog["progresso_atual"] or 0) + increment
            novo_status = "concluido" if novo_progresso >= objetivo["meta_valor"] else "progresso"
        db.execute(
            "UPDATE objetivos_progress SET progresso_atual=%s, status=%s, ultima_atualizacao=%s WHERE id=%s",
            (novo_progresso, novo_status, now, prog["id"])
        )
    else:
        pid = str(uuid.uuid4())
        novo_progresso = min(increment, objetivo["meta_valor"])
        novo_status = "concluido" if novo_progresso >= objetivo["meta_valor"] else "progresso"
        db.execute(
            "INSERT INTO objetivos_progress (id, objetivo_id, user_key, progresso_atual, status, ultimo_reset, ultima_atualizacao, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, oid, user["key"], novo_progresso, novo_status, now, now, now)
        )

    if novo_status == "concluido":
        if objetivo["tipo_progresso"] != "sequencia":
            _award_dcoins(db, user["key"], objetivo["recompensa_dcoins"],
                          f"Objetivo concluído: {objetivo['nome']}")
            _update_streak(db, user["key"])
        else:
            _update_streak(db, user["key"])

    _log_objective_audit(db, oid, user["key"], "incrementar",
                         f"Incremento de {increment}: {novo_progresso}/{objetivo['meta_valor']} (status: {novo_status})")
    db.commit()
    ev = "objective_completed" if novo_status == "concluido" else "objective_updated"
    ws_emit_to_user(user["key"], ev, {"id": oid, "user_key": user["key"], "status": novo_status, "progresso": novo_progresso, "nome": objetivo["nome"]})
    return {"ok": True, "status": novo_status, "progresso": novo_progresso}

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

@app.get("/api/metricas/objetivos/concluidos")
def get_metric_objetivos_concluidos(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        """SELECT COUNT(*) as cnt FROM objetivos_progress op
           JOIN objetivos_def od ON od.id = op.objetivo_id
           WHERE op.user_key=%s AND op.status='concluido' AND od.ativo=1""",
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
        task_tipo = "gestor" if dest_key != user["key"] else "colaborador"
        db.execute(
            """INSERT INTO tarefas (id, titulo, descricao, tipo, criado_por, destinatario_id, prazo, concluida, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s)""",
            (tid, safe_titulo, safe_descricao, task_tipo, user["key"], dest_key, prazo, now, now)
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

    _auto_progress_tarefas(db, user["key"])

    tipo_atv = "tarefa_gestor" if tarefa.get("tipo") == "gestor" else "tarefa_rotina"
    _log_atividade(db, tipo_atv, user["key"],
                   f"{user['name']} concluiu {'uma Tarefa do Gestor' if tipo_atv == 'tarefa_gestor' else 'uma Tarefa'}")

    db.commit()
    return {"ok": True}


# ── TAREFAS — NOVAS ROTAS ─────────────────────────────────────────────────────

def _can_assign(user: dict) -> bool:
    return bool(
        user.get("is_admin") or
        user.get("is_admin_user") or
        user.get("is_rh") or
        user.get("is_diretor") or
        user.get("is_leader") or
        user.get("org_position") in ("gestor", "lider")
    )


@app.get("/api/tarefas/listar")
def listar_tarefas(
    filtro: str = "todas",
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    hoje = datetime.date.today().isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    user_key = user["key"]

    # Auto-atualizar tarefas em andamento com prazo vencido para atrasadas
    db.execute(
        """UPDATE tarefas SET status = 'atrasada', delayed_at = %s
           WHERE destinatario_id = %s
           AND status = 'andamento'
           AND prazo < %s
           AND concluida = 0""",
        (agora, user_key, hoje)
    )

    base_query = """SELECT t.*,
           u.name AS destinatario_nome, u.initials AS destinatario_initials,
           u.color AS destinatario_color,
           c.name AS criador_nome,
           d.name AS delegado_nome
    FROM tarefas t
    LEFT JOIN users u ON u.key = t.destinatario_id
    LEFT JOIN users c ON c.key = t.criado_por
    LEFT JOIN users d ON d.key = t.delegated_by
    WHERE t.destinatario_id = %s AND t.concluida = 0"""

    if filtro == "hoje":
        query = base_query + " AND t.prazo = %s ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (user_key, hoje)).fetchall()
    elif filtro == "amanha":
        amanha = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        query = base_query + " AND t.prazo = %s ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (user_key, amanha)).fetchall()
    elif filtro == "semana":
        fim_semana = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        query = base_query + " AND t.prazo <= %s ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (user_key, fim_semana)).fetchall()
    else:
        query = base_query + " ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (user_key,)).fetchall()

    return [dict(r) for r in rows]


@app.get("/api/tarefas/atribuidas")
def listar_tarefas_atribuidas(
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    hoje = datetime.date.today().isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    user_key = user["key"]

    # Auto-atualizar tarefas em andamento com prazo vencido
    db.execute(
        """UPDATE tarefas SET status = 'atrasada', delayed_at = %s
           WHERE destinatario_id = %s
           AND status = 'andamento'
           AND prazo < %s
           AND concluida = 0""",
        (agora, user_key, hoje)
    )

    rows = db.execute(
        """SELECT t.*,
           u.name AS destinatario_nome, u.initials AS destinatario_initials,
           u.color AS destinatario_color,
           c.name AS criador_nome,
           d.name AS delegado_nome
        FROM tarefas t
        LEFT JOIN users u ON u.key = t.destinatario_id
        LEFT JOIN users c ON c.key = t.criado_por
        LEFT JOIN users d ON d.key = t.delegated_by
        WHERE t.destinatario_id = %s
        AND t.criado_por != %s
        AND t.concluida = 0
        ORDER BY t.prazo ASC, t.created_at DESC""",
        (user_key, user_key)
    ).fetchall()

    return [dict(r) for r in rows]


@app.get("/api/tarefas/historico")
def listar_historico_tarefas(
    status_filter: str = "",
    colaborador_filter: str = "",
    data_inicio: str = "",
    data_fim: str = "",
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    user_key = user["key"]
    conditions = ["(t.destinatario_id = %s OR t.criado_por = %s)"]
    params = [user_key, user_key]

    if status_filter:
        conditions.append("t.status = %s")
        params.append(status_filter)
    if colaborador_filter:
        conditions.append("t.destinatario_id = %s")
        params.append(colaborador_filter)
    if data_inicio:
        conditions.append("t.prazo >= %s")
        params.append(data_inicio)
    if data_fim:
        conditions.append("t.prazo <= %s")
        params.append(data_fim)

    where = " AND ".join(conditions)
    rows = db.execute(
        f"""SELECT t.*,
           u.name AS destinatario_nome, u.initials AS destinatario_initials,
           u.color AS destinatario_color,
           c.name AS criador_nome,
           d.name AS delegado_nome
        FROM tarefas t
        LEFT JOIN users u ON u.key = t.destinatario_id
        LEFT JOIN users c ON c.key = t.criado_por
        LEFT JOIN users d ON d.key = t.delegated_by
        WHERE {where}
        AND (t.concluida = 1 OR t.status IN ('atrasada', 'interrompida', 'cancelada'))
        ORDER BY t.updated_at DESC
        LIMIT 200""",
        params
    ).fetchall()

    return [dict(r) for r in rows]


@app.get("/api/tarefas/kpi")
def get_tarefas_kpi(user=Depends(get_current_user), db=Depends(get_db)):
    hoje = datetime.date.today().isoformat()
    user_key = user["key"]

    # Auto-atualizar atrasadas
    agora = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE tarefas SET status = 'atrasada', delayed_at = %s WHERE destinatario_id = %s AND status = 'andamento' AND prazo < %s AND concluida = 0",
        (agora, user_key, hoje)
    )

    pendentes = db.execute(
        "SELECT COUNT(*) as c FROM tarefas WHERE destinatario_id = %s AND status = 'pendente' AND concluida = 0",
        (user_key,)
    ).fetchone()["c"]

    andamento = db.execute(
        "SELECT COUNT(*) as c FROM tarefas WHERE destinatario_id = %s AND status = 'andamento' AND concluida = 0",
        (user_key,)
    ).fetchone()["c"]

    concluidas_hoje = db.execute(
        "SELECT COUNT(*) as c FROM tarefas WHERE destinatario_id = %s AND concluida = 1 AND DATE(concluida_em) = %s",
        (user_key, hoje)
    ).fetchone()["c"]

    atrasadas = db.execute(
        "SELECT COUNT(*) as c FROM tarefas WHERE destinatario_id = %s AND status = 'atrasada' AND concluida = 0",
        (user_key,)
    ).fetchone()["c"]

    tempo_total = db.execute(
        "SELECT COALESCE(SUM(duration_seconds), 0) as s FROM tarefas WHERE destinatario_id = %s AND concluida = 1",
        (user_key,)
    ).fetchone()["s"]

    return {
        "pendentes": pendentes or 0,
        "andamento": andamento or 0,
        "concluidas_hoje": concluidas_hoje or 0,
        "atrasadas": atrasadas or 0,
        "tempo_produtivo": tempo_total or 0,
    }


@app.post("/api/tarefas/nova")
def criar_nova_tarefa(
    body: NovaTarefaRequest,
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    safe_titulo = _sanitize_text(body.titulo)
    safe_descricao = _sanitize_text(body.descricao) if body.descricao else ""
    if not safe_titulo:
        raise HTTPException(status_code=422, detail="Título é obrigatório.")

    hoje = datetime.date.today().isoformat()
    prazo = body.prazo
    if prazo < hoje:
        raise HTTPException(status_code=422, detail="Prazo não pode ser no passado.")

    now = datetime.datetime.utcnow().isoformat()
    tid = str(uuid.uuid4())

    destinatario_id = user["key"]
    delegado_por = None

    # Se usuário tem permissão para atribuir para outro
    if body.atribuir_para and body.atribuir_para != user["key"]:
        if not _can_assign(user):
            raise HTTPException(status_code=403, detail="Você não tem permissão para atribuir tarefas.")
        destinatario_id = body.atribuir_para
        delegado_por = user["key"]

    tipo = "gestor" if destinatario_id != user["key"] else "colaborador"

    prioridade = body.prioridade if body.prioridade in ("alta", "media", "baixa") else "media"
    recorrencia = body.recorrencia if body.recorrencia in ("diaria", "semanal", "mensal") else "nenhuma"

    db.execute(
        """INSERT INTO tarefas
           (id, titulo, descricao, tipo, tipo_tarefa, prioridade, recorrencia,
            criado_por, destinatario_id, prazo, status, concluida,
            delegated_by, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (tid, safe_titulo, safe_descricao, tipo, body.tipo_tarefa, prioridade, recorrencia,
         user["key"], destinatario_id, prazo, 'pendente', 0,
         delegado_por, now, now)
    )

    # Log tarefas history
    _log_task_history(db, tid, "criada", user["key"], user["name"], f"Tarefa criada: {safe_titulo}")

    if destinatario_id != user["key"]:
        _notify(db, title="📋 Nova tarefa atribuída",
                message=f"{user['name']} atribuiu a tarefa: {safe_titulo}",
                ntype="system", target_user_key=destinatario_id,
                sender_key=user["key"], sender_name=user["name"],
                reference_id=tid, play_sound=True)

    db.commit()
    return {"ok": True, "id": tid}


@app.patch("/api/tarefas/{tarefa_id}/iniciar")
def iniciar_tarefa(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["destinatario_id"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode iniciar uma tarefa que não é sua.")

    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE tarefas SET status='andamento', started_at=%s, updated_at=%s WHERE id=%s",
        (now, now, tarefa_id)
    )
    _log_task_history(db, tarefa_id, "iniciada", user["key"], user["name"], "Tarefa iniciada")
    db.commit()
    return {"ok": True}


@app.patch("/api/tarefas/{tarefa_id}/pausar")
def pausar_tarefa(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["destinatario_id"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode pausar uma tarefa que não é sua.")
    if tarefa["status"] != "andamento":
        raise HTTPException(status_code=400, detail="Tarefa não está em andamento.")

    now = datetime.datetime.utcnow().isoformat()
    started = tarefa.get("started_at")
    elapsed = 0
    if started:
        try:
            started_dt = datetime.datetime.fromisoformat(started)
            now_dt = datetime.datetime.utcnow()
            elapsed = int((now_dt - started_dt).total_seconds())
        except:
            pass

    current_paused = tarefa.get("paused_seconds") or 0
    new_paused = current_paused + elapsed

    db.execute(
        "UPDATE tarefas SET status='pendente', paused_seconds=%s, started_at=NULL, updated_at=%s WHERE id=%s",
        (new_paused, now, tarefa_id)
    )
    _log_task_history(db, tarefa_id, "pausada", user["key"], user["name"], "Tarefa pausada")
    db.commit()
    return {"ok": True}


@app.patch("/api/tarefas/{tarefa_id}/interromper")
def interromper_tarefa(tarefa_id: str, body: InterromperTarefaRequest = None,
                        user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["destinatario_id"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode interromper uma tarefa que não é sua.")

    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE tarefas SET status='interrompida', updated_at=%s WHERE id=%s",
        (now, tarefa_id)
    )
    _log_task_history(db, tarefa_id, "interrompida", user["key"], user["name"], "Tarefa interrompida")
    db.commit()
    return {"ok": True}


@app.patch("/api/tarefas/{tarefa_id}/concluir-agora")
def concluir_tarefa_agora(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["destinatario_id"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode concluir uma tarefa que não é sua.")

    now = datetime.datetime.utcnow().isoformat()
    started = tarefa.get("started_at")
    paused = tarefa.get("paused_seconds") or 0
    elapsed = 0
    if started:
        try:
            started_dt = datetime.datetime.fromisoformat(started)
            now_dt = datetime.datetime.utcnow()
            elapsed = int((now_dt - started_dt).total_seconds())
        except:
            pass

    total_duration = paused + elapsed

    db.execute(
        "UPDATE tarefas SET status='concluida', concluida=1, concluida_em=%s, ended_at=%s, duration_seconds=%s, started_at=NULL, updated_at=%s WHERE id=%s",
        (now, now, total_duration, now, tarefa_id)
    )

    tipo_atv = "tarefa_gestor" if tarefa.get("tipo") == "gestor" else "tarefa_rotina"
    _log_atividade(db, tipo_atv, user["key"],
                   f"{user['name']} concluiu a tarefa: {tarefa.get('titulo', '')}")
    _auto_progress_tarefas(db, user["key"])

    _log_task_history(db, tarefa_id, "concluida", user["key"], user["name"],
                      f"Tarefa concluída. Duração: {total_duration}s")

    db.commit()
    return {"ok": True}


@app.patch("/api/tarefas/{tarefa_id}/justificar-atraso")
def justificar_atraso(tarefa_id: str, body: JustificarAtrasoRequest,
                       user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["destinatario_id"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode justificar esta tarefa.")
    if not body.delay_reason or not body.delay_reason.strip():
        raise HTTPException(status_code=422, detail="Motivo do atraso é obrigatório.")

    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE tarefas SET status='atrasada', delay_reason=%s, delayed_at=%s, updated_at=%s WHERE id=%s",
        (body.delay_reason.strip(), now, now, tarefa_id)
    )
    _log_task_history(db, tarefa_id, "atrasada", user["key"], user["name"],
                      f"Atraso justificado: {body.delay_reason.strip()}")
    db.commit()
    return {"ok": True}


@app.put("/api/tarefas/{tarefa_id}")
def editar_tarefa(tarefa_id: str, body: EditarTarefaRequest,
                   user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["criado_por"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você só pode editar tarefas criadas por você.")

    updates = []
    params = []
    for field in ("titulo", "descricao", "tipo_tarefa", "prioridade", "prazo", "recorrencia", "custom_status"):
        val = getattr(body, field, None)
        if val is not None:
            if field == "titulo":
                val = _sanitize_text(val)
            elif field == "descricao":
                val = _sanitize_text(val)
            updates.append(f"{field} = %s")
            params.append(val)

    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    now = datetime.datetime.utcnow().isoformat()
    updates.append("updated_at = %s")
    params.append(now)
    params.append(tarefa_id)

    db.execute(
        f"UPDATE tarefas SET {', '.join(updates)} WHERE id = %s",
        params
    )
    _log_task_history(db, tarefa_id, "editada", user["key"], user["name"], "Tarefa editada")
    db.commit()
    return {"ok": True}


@app.delete("/api/tarefas/{tarefa_id}")
def excluir_tarefa(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    if tarefa["criado_por"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você só pode excluir tarefas criadas por você.")

    db.execute("DELETE FROM task_comments WHERE tarefa_id = %s", (tarefa_id,))
    db.execute("DELETE FROM task_history WHERE tarefa_id = %s", (tarefa_id,))
    db.execute("DELETE FROM tarefas WHERE id = %s", (tarefa_id,))

    db.commit()
    return {"ok": True}


# ── TASK COMMENTS ────────────────────────────────────────────────────────────

@app.get("/api/tarefas/{tarefa_id}/comentarios")
def get_task_comments(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM task_comments WHERE tarefa_id = %s ORDER BY created_at ASC",
        (tarefa_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/tarefas/{tarefa_id}/comentarios")
def add_task_comment(tarefa_id: str, body: ComentarTarefaRequest,
                      user=Depends(get_current_user), db=Depends(get_db)):
    tarefa = db.execute("SELECT * FROM tarefas WHERE id=%s", (tarefa_id,)).fetchone()
    if not tarefa:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")

    safe_text = _sanitize_text(body.text)
    if not safe_text:
        raise HTTPException(status_code=422, detail="Comentário vazio.")

    now = datetime.datetime.utcnow().isoformat()
    cid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO task_comments (id, tarefa_id, author_key, author_name, text, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
        (cid, tarefa_id, user["key"], user["name"], safe_text, now)
    )
    _log_task_history(db, tarefa_id, "comentario", user["key"], user["name"], f"Comentário: {safe_text[:100]}")
    db.commit()
    return {"ok": True, "id": cid}


# ── TASK HISTORY ─────────────────────────────────────────────────────────────

@app.get("/api/tarefas/{tarefa_id}/historico")
def get_task_history(tarefa_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT * FROM task_history WHERE tarefa_id = %s ORDER BY created_at ASC",
        (tarefa_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _log_task_history(db, tarefa_id: str, action: str, actor_key: str,
                       actor_name: str, detail: str = ""):
    created_at = datetime.datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO task_history (id, tarefa_id, action, actor_key, actor_name, detail, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), tarefa_id, action, actor_key, actor_name, detail, created_at)
    )
    ws_emit("task_updated", {
        "id": tarefa_id,
        "action": action,
        "actor_key": actor_key,
        "actor_name": actor_name,
        "detail": detail,
        "created_at": created_at,
    })


# ── AGENDA / EVENTOS ─────────────────────────────────────────────────────────

@app.get("/api/tarefas/eventos")
def listar_eventos_tarefas(user=Depends(get_current_user), db=Depends(get_db)):
    hoje = datetime.date.today().isoformat()
    fim_semana = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    rows = db.execute(
        """SELECT t.id, t.titulo, t.descricao, t.tipo_tarefa, t.prazo, t.prioridade,
                  t.criado_por, u.name AS criador_nome
           FROM tarefas t
           LEFT JOIN users u ON u.key = t.criado_por
           WHERE t.prazo BETWEEN %s AND %s
           AND t.tipo_tarefa IN ('reuniao', 'treinamento', 'palestra', 'evento', 'lembrete')
           AND (t.destinatario_id = %s OR t.criado_por = %s OR t.tipo_tarefa = 'evento')
           ORDER BY t.prazo ASC""",
        (hoje, fim_semana, user["key"], user["key"])
    ).fetchall()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# BIRTHDAYS
# ═════════════════════════════════════════════════════════════════════════════

_birthday_cache = {"data": None, "timestamp": 0}

def _normalize_birthday_row(row: dict):
    nome = _sanitize_text((row.get("nome") or ""))[:80]
    tipo = _sanitize_text((row.get("tipo") or ""))[:40]
    departamento = _sanitize_text((row.get("departamento") or ""))[:60]
    foto_url = row.get("foto_url") or None

    try:
        dia = int(row.get("dia"))
        mes = int(row.get("mes"))
    except Exception:
        return None

    if dia < 1 or dia > 31 or mes < 1 or mes > 12:
        return None

    return {
        "id": row.get("id"),
        "nome": nome,
        "tipo": tipo,
        "dia": dia,
        "mes": mes,
        "departamento": departamento,
        "foto_url": foto_url,
    }

@app.get("/api/birthdays/current-month")
def get_current_month_birthdays(user=Depends(get_current_user), db=Depends(get_db)):
    # Security: user identity and role come only from validated JWT on backend.
    # We never trust role/user fields from frontend payload for this endpoint.
    _check_birthday_rate_limit(user["key"])

    now = time.time()
    if _birthday_cache["data"] and (now - _birthday_cache["timestamp"]) < 3600:
        return _birthday_cache["data"]

    current_month = datetime.date.today().month
    rows = db.execute("""
        SELECT id, nome, tipo, dia, mes, departamento, foto_url
        FROM aniversarios
        WHERE ativo = true
          AND mes = %s
        ORDER BY dia ASC
    """, (current_month,)).fetchall()

    # Security: strict response shaping + sanitization to mitigate XSS and
    # data leakage of unexpected columns. Only an allowlisted structure is returned.
    result = []
    for r in rows:
        normalized = _normalize_birthday_row(dict(r))
        if not normalized:
            logger.warning("birthday_row_rejected user=%s raw_id=%s", user["key"], dict(r).get("id"))
            continue
        result.append(normalized)

    _birthday_cache["data"] = result
    _birthday_cache["timestamp"] = now
    return result


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
    notif_id = str(uuid.uuid4())
    created_at = datetime.datetime.utcnow().isoformat()
    resolved_audience = audience or ('personal' if target_user_key else 'all')
    db.execute(
        """INSERT INTO notifications
        (id, title, message, type, target_user_key, audience,
            sender_key, sender_name, reference_id, play_sound, is_read, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (notif_id, title, message, ntype,
        target_user_key, resolved_audience,
        sender_key, sender_name, reference_id, play_sound, False,
        created_at)
    )
    payload = {
        "id": notif_id,
        "title": title,
        "message": message,
        "type": ntype,
        "target_user_key": target_user_key,
        "audience": resolved_audience,
        "sender_key": sender_key,
        "sender_name": sender_name,
        "reference_id": reference_id,
        "play_sound": play_sound,
        "is_read": False,
        "created_at": created_at,
    }
    rooms = ["all"]
    if target_user_key:
        rooms = [f"user:{target_user_key}"]
    elif resolved_audience and resolved_audience not in ("all", "personal"):
        rooms = [f"dept:{resolved_audience}"]
    ws_emit("notification_created", payload, rooms=rooms)


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

    conditions.append("n.type IN %s")
    params.append(('comunicado', 'dcash', 'celebration'))

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

@app.delete("/api/notifications")
def reset_notifications(user=Depends(get_current_user), db=Depends(get_db)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Apenas admin pode resetar notificações.")
    _ensure_notifications_table(db)
    db.execute("DELETE FROM notifications")
    db.commit()
    return {"success": True}


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
    _invalidate_user_cache(body.target_user_key)

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
    _invalidate_user_cache(body.target_user_key)

    log_action(
        db, user["key"], body.target_user_key,
        "Posição Organizacional",
        f"org_position definido como: {body.org_position}"
    )
    return {"ok": True}


# ── RA-TIM-BUM ──────────────────────────────────────────────────────────────────

_ratimbum_limits = {}

def _check_ratimbum_rate_limit(user_key: str):
    now = time.time()
    minute = int(now / 60)
    key = f"{user_key}:{minute}"
    count = _ratimbum_limits.get(key, 0)
    if count >= 20:
        raise HTTPException(status_code=429, detail="Limite de ações no RaTimBum excedido. Tente novamente em 1 minuto.")
    _ratimbum_limits[key] = count + 1

def _resolve_mentions(text: str, db):
    mentioned = set()
    for match in re.finditer(r'@([A-Za-z0-9_.-]+)', text or ''):
        key = match.group(1).lower()
        if key == 'todos':
            mentioned.add('@todos')
        else:
            user = db.execute("SELECT key, name FROM users WHERE key=%s", (key,)).fetchone()
            if user:
                mentioned.add(user['key'])
    return list(mentioned)

CELEBRATION_KEYWORDS = [
    'parabéns', 'parabens', 'feliz aniversário', 'feliz aniversario',
    'muitas felicidades', 'congratulações', 'congratulacoes',
    'te parabenizo', 'quero parabenizar',
]

def _is_celebration(text: str) -> int:
    t = text.lower().strip()
    for kw in CELEBRATION_KEYWORDS:
        if kw in t:
            return 1
    return 0

def _format_ratimbum_post(row: dict):
    d = dict(row)
    d["reactions"] = json.loads(d.get("reactions") or "{}")
    d["mentions"] = json.loads(d.get("mentions") or "[]")
    if "is_celebration" not in d:
        d["is_celebration"] = 1
    return d

def _build_post_ws_payload(post_id, text, mentions, user, author_type="user", is_celebration=1):
    return {
        "id": post_id,
        "author_key": user["key"] if author_type == "user" else "system",
        "author_name": user["name"] if author_type == "user" else "Axis",
        "author_initials": user.get("initials", "AX") if author_type == "user" else "AX",
        "author_color": user.get("color", "#C9A84C") if author_type == "user" else "#C9A84C",
        "author_photo_url": user.get("photo_url", "") if author_type == "user" else "",
        "author_role": user.get("role", "") if author_type == "user" else "Sistema",
        "author_type": author_type,
        "text": text,
        "mentions": mentions,
        "reactions": {},
        "is_celebration": is_celebration,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }

_HAS_PARENT_COLUMN = None

def _check_parent_column(db):
    global _HAS_PARENT_COLUMN
    if _HAS_PARENT_COLUMN is None:
        try:
            db.execute("SELECT parent_id FROM ratimbum_posts LIMIT 0")
            _HAS_PARENT_COLUMN = True
        except Exception:
            db.rollback()
            _HAS_PARENT_COLUMN = False
    return _HAS_PARENT_COLUMN

_HAS_CELEBRATION_COLUMN = None

def _check_celebration_column(db):
    global _HAS_CELEBRATION_COLUMN
    if _HAS_CELEBRATION_COLUMN is None:
        try:
            db.execute("SELECT is_celebration FROM ratimbum_posts LIMIT 0")
            _HAS_CELEBRATION_COLUMN = True
        except Exception:
            db.rollback()
            _HAS_CELEBRATION_COLUMN = False
    return _HAS_CELEBRATION_COLUMN

@app.get("/api/ratimbum/posts")
def get_ratimbum_posts(filter: str = "all", limit: int = 30, offset: int = 0,
                       user=Depends(get_current_user), db=Depends(get_db)):
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    user_key = user["key"]

    if filter == "self":
        rows = db.execute(
            """SELECT p.* FROM ratimbum_posts p
               WHERE p.author_key = %s
               ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
            (user_key, limit, offset)
        ).fetchall()
    elif filter == "team":
        manager_key = user.get("manager_key")
        if manager_key:
            team_keys = [r["key"] for r in
                         db.execute("SELECT key FROM users WHERE manager_key=%s",
                                    (manager_key,)).fetchall()]
            team_keys.append(user_key)
        else:
            team_keys = [user_key]
        placeholders = ",".join("%s" for _ in team_keys)
        rows = db.execute(
            f"""SELECT p.* FROM ratimbum_posts p
                WHERE p.author_key IN ({placeholders})
                ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
            team_keys + [limit, offset]
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM ratimbum_posts ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset)
        ).fetchall()

    total = db.execute("SELECT COUNT(*) FROM ratimbum_posts").fetchone()[0]
    result = []
    for r in rows:
        d = _format_ratimbum_post(r)
        d["reply_count"] = 0
        result.append(d)
    return {"posts": result, "total": total}


@app.get("/api/ratimbum/posts/{post_id}/replies")
def get_ratimbum_replies(post_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    if not _check_parent_column(db):
        return {"replies": []}
    parent = db.execute("SELECT id FROM ratimbum_posts WHERE id=%s", (post_id,)).fetchone()
    if not parent:
        raise HTTPException(status_code=404, detail="Post não encontrado.")
    rows = db.execute(
        "SELECT * FROM ratimbum_posts WHERE parent_id=%s ORDER BY created_at ASC",
        (post_id,)
    ).fetchall()
    return {"replies": [_format_ratimbum_post(r) for r in rows]}


@app.post("/api/ratimbum/posts")
def create_ratimbum_post(body: CreateRatimbumPostRequest,
                          user=Depends(get_current_user), db=Depends(get_db)):
    _check_ratimbum_rate_limit(user["key"])
    safe_text = _sanitize_text(body.text or "")
    if not safe_text.strip():
        raise HTTPException(status_code=400, detail="A mensagem não pode estar vazia.")

    mentions = _resolve_mentions(safe_text, db)
    is_celebration = _is_celebration(safe_text)
    post_id = str(uuid.uuid4())
    safe_text_with_mentions = safe_text
    for m in mentions:
        if m == '@todos':
            safe_text_with_mentions = safe_text_with_mentions.replace('@todos', '@todos')
        else:
            user_row = db.execute("SELECT name FROM users WHERE key=%s", (m,)).fetchone()
            if user_row:
                safe_text_with_mentions = safe_text_with_mentions.replace(f'@{m}', f'@{user_row["name"]}')

    has_cele = _check_celebration_column(db)
    extra_col = ", is_celebration" if has_cele else ""
    extra_ph = ", %s" if has_cele else ""
    base_cols = ("id, author_key, author_name, author_initials, author_color, author_photo_url, "
                 "author_role, author_type, text, mentions, reactions, created_at")
    base_phs = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
    vals = [post_id, user["key"], user["name"], user["initials"], user["color"],
            user.get("photo_url", ""), user.get("role", ""),
            'user', safe_text_with_mentions,
            json.dumps(mentions), '{}',
            datetime.datetime.utcnow().isoformat()]
    if has_cele:
        vals.append(is_celebration)
    db.execute(f"INSERT INTO ratimbum_posts ({base_cols}{extra_col}) VALUES ({base_phs}{extra_ph})", vals)

    log_audit(db, user["key"], "ratimbum_post_create", user["key"],
              f"Post criado no RaTimBum: {(safe_text or '')[:80]}")

    if '@todos' in mentions:
        _notify(db, title="🎉 RaTimBum",
                message=f"{user['name']} mencionou @todos no RaTimBum: {(safe_text or '')[:80]}",
                ntype="celebration", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=post_id, play_sound=False)

    for mention_key in mentions:
        if mention_key != '@todos' and mention_key != user["key"]:
            _notify(db, title="👋 Você foi mencionado no RaTimBum",
                    message=f"{user['name']} mencionou você no RaTimBum",
                    ntype="mention", target_user_key=mention_key,
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=post_id, play_sound=True)

    db.commit()
    post_data = _build_post_ws_payload(post_id, safe_text_with_mentions, mentions, user, is_celebration=is_celebration)
    ws_emit("ratimbum_new_post", post_data, rooms=["all"])
    return {"ok": True, "id": post_id, "post": post_data}


@app.post("/api/ratimbum/posts/{post_id}/reply")
def reply_ratimbum_post(post_id: str, body: CreateRatimbumReplyRequest,
                         user=Depends(get_current_user), db=Depends(get_db)):
    _check_ratimbum_rate_limit(user["key"])
    if not _check_parent_column(db):
        raise HTTPException(status_code=400, detail="Respostas ainda não disponíveis. Atualize o banco de dados.")
    parent = db.execute("SELECT id FROM ratimbum_posts WHERE id=%s", (post_id,)).fetchone()
    if not parent:
        raise HTTPException(status_code=404, detail="Post não encontrado.")
    safe_text = _sanitize_text(body.text or "")
    if not safe_text.strip():
        raise HTTPException(status_code=400, detail="A mensagem não pode estar vazia.")

    mentions = _resolve_mentions(safe_text, db)
    is_celebration = _is_celebration(safe_text)
    reply_id = str(uuid.uuid4())
    safe_text_with_mentions = safe_text
    for m in mentions:
        if m == '@todos':
            safe_text_with_mentions = safe_text_with_mentions.replace('@todos', '@todos')
        else:
            user_row = db.execute("SELECT name FROM users WHERE key=%s", (m,)).fetchone()
            if user_row:
                safe_text_with_mentions = safe_text_with_mentions.replace(f'@{m}', f'@{user_row["name"]}')

    has_cele = _check_celebration_column(db)
    extra_col = ", is_celebration" if has_cele else ""
    extra_ph = ", %s" if has_cele else ""
    base_cols = ("id, author_key, author_name, author_initials, author_color, author_photo_url, "
                 "author_role, author_type, text, mentions, reactions, created_at, parent_id")
    base_phs = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
    vals = [reply_id, user["key"], user["name"], user["initials"], user["color"],
            user.get("photo_url", ""), user.get("role", ""),
            'user', safe_text_with_mentions,
            json.dumps(mentions), '{}',
            datetime.datetime.utcnow().isoformat(), post_id]
    if has_cele:
        vals.append(is_celebration)
    db.execute(f"INSERT INTO ratimbum_posts ({base_cols}{extra_col}) VALUES ({base_phs}{extra_ph})", vals)

    db.commit()
    ws_emit("ratimbum_new_reply", {
        "reply": _build_post_ws_payload(reply_id, safe_text_with_mentions, mentions, user,
                  is_celebration=_is_celebration(safe_text)),
        "parent_id": post_id,
    }, rooms=["all"])
    return {"ok": True, "id": reply_id}


@app.delete("/api/ratimbum/posts/{post_id}")
def delete_ratimbum_post(post_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM ratimbum_posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado.")
    if post["author_type"] == "system":
        raise HTTPException(status_code=403, detail="Posts do sistema não podem ser removidos.")
    if post["author_key"] != user["key"] and not user.get("is_admin") and not user.get("is_admin_user"):
        raise HTTPException(status_code=403, detail="Sem permissão para remover este post.")
    db.execute("DELETE FROM ratimbum_reactions WHERE post_id=%s", (post_id,))
    if _check_parent_column(db):
        db.execute("DELETE FROM ratimbum_posts WHERE parent_id=%s", (post_id,))
    db.execute("DELETE FROM ratimbum_posts WHERE id=%s", (post_id,))
    log_audit(db, user["key"], "ratimbum_post_delete", user["key"],
              f"Post removido do RaTimBum: {(post.get('text') or '')[:80]}")
    db.commit()
    ws_emit("ratimbum_delete_post", {"id": post_id}, rooms=["all"])
    return {"ok": True}


@app.post("/api/ratimbum/posts/{post_id}/reactions")
def add_ratimbum_reaction(post_id: str, body: ReactRatimbumRequest,
                           user=Depends(get_current_user), db=Depends(get_db)):
    _check_ratimbum_rate_limit(user["key"])
    post = db.execute("SELECT * FROM ratimbum_posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado.")

    emoji = body.emoji.strip()
    if not emoji:
        raise HTTPException(status_code=400, detail="Emoji inválido.")

    existing = db.execute(
        "SELECT id FROM ratimbum_reactions WHERE post_id=%s AND user_key=%s AND emoji=%s",
        (post_id, user["key"], emoji)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Você já reagiu com este emoji.")

    reaction_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO ratimbum_reactions (id, post_id, user_key, emoji, created_at) VALUES (%s,%s,%s,%s,%s)",
        (reaction_id, post_id, user["key"], emoji, datetime.datetime.utcnow().isoformat())
    )

    reactions = json.loads(post.get("reactions") or "{}")
    reactions.setdefault(emoji, [])
    if user["key"] not in reactions[emoji]:
        reactions[emoji].append(user["key"])
    db.execute("UPDATE ratimbum_posts SET reactions=%s WHERE id=%s",
               (json.dumps(reactions), post_id))

    if post["author_key"] != user["key"]:
        _notify(db, title="🎉 Reação no RaTimBum",
                message=f"{user['name']} reagiu com {emoji} ao seu post",
                ntype="ratimbum_reaction", target_user_key=post["author_key"],
                sender_key=user["key"], sender_name=user["name"],
                reference_id=post_id, play_sound=False)

    db.commit()
    ws_emit("ratimbum_update_post", {"id": post_id, "reactions": reactions}, rooms=["all"])
    return {"reactions": reactions}


@app.delete("/api/ratimbum/posts/{post_id}/reactions")
def remove_ratimbum_reaction(post_id: str, body: ReactRatimbumRequest,
                              user=Depends(get_current_user), db=Depends(get_db)):
    _check_ratimbum_rate_limit(user["key"])
    post = db.execute("SELECT * FROM ratimbum_posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado.")

    emoji = body.emoji.strip()
    if not emoji:
        raise HTTPException(status_code=400, detail="Emoji inválido.")

    existing = db.execute(
        "SELECT id FROM ratimbum_reactions WHERE post_id=%s AND user_key=%s AND emoji=%s",
        (post_id, user["key"], emoji)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Reação não encontrada.")

    db.execute("DELETE FROM ratimbum_reactions WHERE id=%s", (existing["id"],))

    reactions = json.loads(post.get("reactions") or "{}")
    users_list = reactions.get(emoji, [])
    if user["key"] in users_list:
        users_list.remove(user["key"])
    if not users_list:
        reactions.pop(emoji, None)
    else:
        reactions[emoji] = users_list
    db.execute("UPDATE ratimbum_posts SET reactions=%s WHERE id=%s",
               (json.dumps(reactions), post_id))

    db.commit()
    ws_emit("ratimbum_update_post", {"id": post_id, "reactions": reactions}, rooms=["all"])
    return {"reactions": reactions}


@app.get("/api/ratimbum/users")
def search_ratimbum_users(q: str = "", user=Depends(get_current_user), db=Depends(get_db)):
    if not q.strip():
        rows = db.execute(
            "SELECT key, name, initials, role, photo_url, color FROM users ORDER BY name LIMIT 20"
        ).fetchall()
    else:
        safe_q = q.strip().lower()
        rows = db.execute(
            """SELECT key, name, initials, role, photo_url, color FROM users
               WHERE LOWER(name) LIKE %s OR LOWER(key) LIKE %s
               ORDER BY name LIMIT 20""",
            (f"%{safe_q}%", f"%{safe_q}%")
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/ratimbum/birthdays/next")
def get_next_birthday(user=Depends(get_current_user), db=Depends(get_db)):
    today = datetime.date.today()
    rows = db.execute(
        """SELECT id, nome, tipo, dia, mes, departamento, foto_url
           FROM aniversarios WHERE ativo = true ORDER BY mes, dia""",
    ).fetchall()
    next_bday = None
    for r in rows:
        dia = int(r["dia"])
        mes = int(r["mes"])
        bday = datetime.date(today.year, mes, dia)
        if bday < today:
            bday = datetime.date(today.year + 1, mes, dia)
        if next_bday is None or bday < next_bday["date"]:
            next_bday = {"date": bday, "row": r}
    if not next_bday:
        return {"birthday": None}
    b = next_bday["row"]
    return {
        "birthday": {
            "id": b.get("id"),
            "nome": _sanitize_text(b.get("nome", ""))[:80],
            "departamento": _sanitize_text(b.get("departamento", ""))[:60],
            "dia": int(b["dia"]),
            "mes": int(b["mes"]),
            "foto_url": b.get("foto_url") or None,
            "days_until": (next_bday["date"] - today).days,
        }
    }


@app.get("/api/ratimbum/birthdays/month")
def get_month_birthdays(user=Depends(get_current_user), db=Depends(get_db)):
    current_month = datetime.date.today().month
    today = datetime.date.today()
    rows = db.execute(
        """SELECT id, nome, tipo, dia, mes, departamento, foto_url
           FROM aniversarios WHERE ativo = true AND mes = %s ORDER BY dia ASC""",
        (current_month,)
    ).fetchall()
    result = []
    for r in rows:
        dia = int(r["dia"])
        bday = datetime.date(today.year, current_month, dia)
        diff = (bday - today).days
        if diff < 0:
            tag = "past"
        elif diff == 0:
            tag = "today"
        elif diff <= 7:
            tag = "soon"
        else:
            tag = "month"
        result.append({
            "id": r.get("id"),
            "nome": _sanitize_text(r.get("nome", ""))[:80],
            "departamento": _sanitize_text(r.get("departamento", ""))[:60],
            "dia": dia,
            "mes": current_month,
            "foto_url": r.get("foto_url") or None,
            "tag": tag,
        })
    return {"birthdays": result}


@app.get("/api/ratimbum/stats/month")
def get_ratimbum_month_stats(user=Depends(get_current_user), db=Depends(get_db)):
    first_day = datetime.date.today().replace(day=1).isoformat()
    next_month = (datetime.date.today().replace(day=28) + datetime.timedelta(days=4)).replace(day=1).isoformat()
    posts_count = db.execute(
        "SELECT COUNT(*) FROM ratimbum_posts WHERE created_at >= %s AND created_at < %s",
        (first_day, next_month)
    ).fetchone()[0]
    reactions_count = db.execute(
        "SELECT COUNT(*) FROM ratimbum_reactions r JOIN ratimbum_posts p ON r.post_id=p.id WHERE p.created_at >= %s AND p.created_at < %s",
        (first_day, next_month)
    ).fetchone()[0]
    current_month = datetime.date.today().month
    birthdays_count = db.execute(
        "SELECT COUNT(*) FROM aniversarios WHERE ativo=true AND mes=%s",
        (current_month,)
    ).fetchone()[0]
    unique_authors = db.execute(
        "SELECT COUNT(DISTINCT author_key) FROM ratimbum_posts WHERE created_at >= %s AND created_at < %s AND author_type='user'",
        (first_day, next_month)
    ).fetchone()[0]
    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    engagement = round((unique_authors / max(total_users, 1)) * 100, 1)
    return {
        "messages": posts_count,
        "reactions": reactions_count,
        "birthdays": birthdays_count,
        "engagement": engagement,
    }


@app.get("/api/ratimbum/stats/top")
def get_ratimbum_top_contributors(user=Depends(get_current_user), db=Depends(get_db)):
    first_day = datetime.date.today().replace(day=1).isoformat()
    next_month = (datetime.date.today().replace(day=28) + datetime.timedelta(days=4)).replace(day=1).isoformat()
    rows = db.execute(
        """SELECT p.author_key, p.author_name, p.author_initials, p.author_color,
                  p.author_photo_url, p.author_role, COUNT(*) as cnt
           FROM ratimbum_posts p
           WHERE p.created_at >= %s AND p.created_at < %s AND p.author_type='user'
           GROUP BY p.author_key, p.author_name, p.author_initials, p.author_color,
                    p.author_photo_url, p.author_role
           ORDER BY cnt DESC LIMIT 3""",
        (first_day, next_month)
    ).fetchall()
    return {"top": [dict(r) for r in rows]}


# ── Job: Post automático de aniversário (chamado por scheduler externo ou manualmente) ──
@app.post("/api/ratimbum/system-birthday-post")
def system_birthday_post(body: dict, user=Depends(require_level(3)), db=Depends(get_db)):
    user_key = (body or {}).get("user_key", "")
    target = db.execute("SELECT * FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    text = f"Hoje é aniversário de @{target['name']}! 🎂 Parabenize-o(a)!"
    post_id = str(uuid.uuid4())
    has_cele = _check_celebration_column(db)
    extra_col = ", is_celebration" if has_cele else ""
    extra_ph = ", %s" if has_cele else ""
    base_cols = ("id, author_key, author_name, author_initials, author_color, author_photo_url, "
                 "author_role, author_type, text, mentions, reactions, created_at")
    base_phs = "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s"
    vals = [post_id, 'system', 'Axis', 'AX', '#C9A84C', '', 'Sistema', 'system',
            text, json.dumps(['@todos']), '{}', datetime.datetime.utcnow().isoformat()]
    if has_cele:
        vals.append(1)
    db.execute(f"INSERT INTO ratimbum_posts ({base_cols}{extra_col}) VALUES ({base_phs}{extra_ph})", vals)
    log_audit(db, 'system', 'ratimbum_system_birthday', user_key,
              f"Post automático de aniversário para {target['name']}")
    db.commit()
    _notify(db, title="🎂 Aniversário!",
            message=f"Hoje é aniversário de {target['name']}! 🎉",
            ntype="celebration", audience="all",
            sender_key='system', sender_name='Axis',
            reference_id=post_id, play_sound=True)
    ws_emit("ratimbum_new_post", {
        "id": post_id,
        "author_key": 'system',
        "author_name": 'Axis',
        "author_initials": 'AX',
        "author_color": '#C9A84C',
        "author_photo_url": '',
        "author_role": 'Sistema',
        "author_type": 'system',
        "text": text,
        "mentions": ['@todos'],
        "reactions": {},
        "is_celebration": 1,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }, rooms=["all"])
    return {"ok": True, "id": post_id}


@app.get("/api/ratimbum/online")
def ratimbum_online_users(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT p.user_key, u.name, u.initials, u.color, u.photo_url, u.role
        FROM presence p
        JOIN users u ON u.key = p.user_key
        WHERE p.is_online = 1
        ORDER BY u.name ASC
    """).fetchall()
    return {"online": [dict(r) for r in rows]}



# -- EVENTOS ---------------------------------------------------------
@app.get("/api/events")
def get_events(user=Depends(get_current_user), db=Depends(get_db)):
    today = datetime.date.today().isoformat()
    row = db.execute("""
        SELECT id, name, event_date, image_url, created_at
        FROM events
        WHERE event_date >= %s
        ORDER BY event_date ASC
        LIMIT 1
    """, (today,)).fetchone()
    if not row:
        return {"event": None}
    return {"event": dict(row)}

# -- EVENTO (card APNG) ----------------------------------------------
@app.get("/api/evento")
def get_evento(user=Depends(get_current_user), db=Depends(get_db)):
    today = datetime.date.today().isoformat()
    row = db.execute("""
        SELECT id, titulo, data_inicio, data_termino, apng_url, created_at
        FROM evento
        WHERE data_termino >= %s
        ORDER BY data_inicio ASC
        LIMIT 1
    """, (today,)).fetchone()
    if not row:
        return {"evento": None}
    return {"evento": dict(row)}

# Expose a unified ASGI app (FastAPI + Socket.IO)
app = socketio.ASGIApp(sio, app)
