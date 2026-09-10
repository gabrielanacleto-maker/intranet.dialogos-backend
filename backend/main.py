from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, status, Request, Header, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import os, io, uuid, shutil, datetime, json, re, time, asyncio, threading
from urllib.parse import urlparse, parse_qs, quote
from pathlib import Path
import logging

from pydantic import BaseModel

from models import *
from database import get_db, init_db, get_db_context, seed_estrutura_padrao
from deps import (security, get_current_user, get_current_user_from_token,
                  get_optional_user, require_level, log_action, _invalidate_user_cache)
from auth import create_token, verify_token, hash_password, check_password
from rh_estrutura import router as rh_estrutura_router
from disc import router as disc_router

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
        global _sio_loop
        _sio_loop = asyncio.get_running_loop()
        init_db()
        try:
            yield
        finally:
            from database import close_pool
            close_pool()

cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET")
    )

app = FastAPI(title="Intranet Diálogos API", lifespan=lifespan)

app.include_router(rh_estrutura_router)
app.include_router(disc_router)

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
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=origins,
    logger=False,
    engineio_logger=False,
)

_sio_loop = None

def _schedule_sio_emit(coro):
    if _sio_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, _sio_loop)
    except Exception:
        logger.exception("socket_emit_failed")

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

_presence = {}
_PRESENCE_TIMEOUT = 60

def _presence_user_list():
    return sorted(_presence.values(), key=lambda u: u["name"].lower())

def _emit_presence():
    _schedule_sio_emit(sio.emit("presence_update", {
        "online_count": len(_presence),
        "users": _presence_user_list(),
    }, room="all"))

def _cleanup_stale_presence():
    now = time.time()
    stale = [k for k, v in list(_presence.items()) if now - v["last_ping"] > _PRESENCE_TIMEOUT]
    for k in stale:
        _presence.pop(k, None)
    if stale:
        _emit_presence()

def _fetch_user_for_socket(user_key: str):
    with get_db_context() as db:
        user_row = db.execute("SELECT * FROM users WHERE key=%s", (user_key,)).fetchone()
        if not user_row:
            return None
        return dict(user_row)


@sio.event
async def connect(sid, environ, auth=None):
    token = _extract_socket_token(environ, auth)
    if not token:
        raise ConnectionRefusedError("unauthorized")
    payload = verify_token(token)
    if not payload or not payload.get("sub"):
        raise ConnectionRefusedError("unauthorized")
    user = await asyncio.to_thread(_fetch_user_for_socket, payload["sub"])
    if user is None:
        raise ConnectionRefusedError("unauthorized")
    await sio.save_session(sid, {
        "user_key": user["key"],
        "dept": user.get("dept", ""),
        "name": user["name"],
        "initials": user.get("initials", user["name"][0] if user["name"] else "?"),
        "color": user.get("color", "#C9A84C"),
        "photo_url": user.get("photo_url", ""),
        "role": user.get("role", ""),
    })
    await sio.enter_room(sid, "all")
    await sio.enter_room(sid, f"user:{user['key']}")
    if user.get("dept"):
        await sio.enter_room(sid, f"dept:{user['dept']}")
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
async def disconnect(sid):
    try:
        session = await sio.get_session(sid)
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
async def ping(sid):
    try:
        session = await sio.get_session(sid)
    except Exception:
        session = None
    if session and session.get("user_key"):
        ukey = session["user_key"]
        if ukey in _presence:
            _presence[ukey]["last_ping"] = time.time()
    _cleanup_stale_presence()

@sio.event
async def join(sid, data):
    room = (data or {}).get("room")
    if room:
        await sio.enter_room(sid, room)

@sio.event
async def leave(sid, data):
    room = (data or {}).get("room")
    if room:
        await sio.leave_room(sid, room)

def ws_emit(event: str, payload: dict, rooms=None):
    try:
        if rooms:
            for room in rooms:
                _schedule_sio_emit(sio.emit(event, payload, room=room))
            return
        _schedule_sio_emit(sio.emit(event, payload, room="all"))
    except Exception:
        logger.exception("socket_emit_failed event=%s", event)

def ws_emit_to_user(user_key: str, event: str, payload: dict):
    try:
        _schedule_sio_emit(sio.emit(event, payload, room=f"user:{user_key}"))
    except Exception:
        logger.exception("socket_emit_to_user_failed event=%s user=%s", event, user_key)

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
        ident = body.key.strip().lower()
        if "@" in ident:
            user = db.execute("SELECT * FROM users WHERE LOWER(email)=%s", (ident,))
            user = db.fetchone()
        else:
            user = db.execute("SELECT * FROM users WHERE key=%s", (ident,))
            user = db.fetchone()
        if not user or not check_password(body.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        if user.get("desligado"):
            raise HTTPException(status_code=403, detail="Conta desligada. Contate a administração.")
        token = create_token({"sub": user["key"], "level": user["access_level"]})
        return {
            "token": token,
            "must_change_password": not user["password_changed"],
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
                "cargo_id": user.get("cargo_id"),
                "senioridade_id": user.get("senioridade_id"),
                "departamento_id": user.get("departamento_id"),
                "empresa_id": user.get("empresa_id"),
                "disc": user.get("disc", ""),
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
        "hire_date": user.get("hire_date", ""),
        "cargo_id": user.get("cargo_id"),
        "senioridade": user.get("senioridade", ""),
        "senioridade_id": user.get("senioridade_id"),
        "departamento_id": user.get("departamento_id"),
        "empresa_id": user.get("empresa_id"),
        "disc": user.get("disc", ""),
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

# ── FORGOT PASSWORD ─────────────────────────────────────────────────────────
@app.post("/api/auth/forgot-password")
def forgot_password(body: ForgotPasswordRequest, request: Request, db=Depends(get_db)):
    email = body.email.strip().lower()
    user = db.execute("SELECT * FROM users WHERE LOWER(email)=%s", (email,)).fetchone()
    
    # Sempre retorna sucesso por segurança
    if not user:
        return {"ok": True, "message": "Se o e-mail existir, você receberá um link de recuperação."}
    
    # Gerar token único
    token = str(uuid.uuid4())
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(hours=1)
    
    # Salvar token no banco
    db.execute(
        "INSERT INTO password_reset_tokens (id, email, token, created_at, expires_at, used) VALUES (%s, %s, %s, %s, %s, 0)",
        (str(uuid.uuid4()), email, token, now.isoformat(), expires_at.isoformat())
    )
    db.commit()
    
    # Enviar e-mail com Resend
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY")
        
        reset_link = f"{request.base_url}reset-password?token={token}"
        
        html_content = f"""<html><body style="font-family: Arial;">
            <h2>Redefinição de Senha - Clínica Diálogos</h2>
            <p>Olá, {user["name"]}!</p>
            <p>Clique no link para redefinir sua senha:</p>
            <a href="{reset_link}">Redefinir Senha</a>
            <p>Este link expira em 1 hora.</p>
        </body></html>"""
        
        params = {
            "from": "Clínica Diálogos <noreply@axisdiálogos.com>",
            "to": [email],
            "subject": "Redefinição de Senha",
            "html": html_content
        }
        
        resend.Emails.send(params)
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail: {str(e)}")
    
    return {"ok": True, "message": "Se o e-mail existir, você receberá um link."}

@app.get("/api/auth/validate-reset-token")
def validate_reset_token(token: str, db=Depends(get_db)):
    token_data = db.execute(
        "SELECT * FROM password_reset_tokens WHERE token=%s AND used=0",
        (token,)
    ).fetchone()
    
    if not token_data:
        raise HTTPException(status_code=400, detail="Token inválido.")
    
    expires_at = datetime.datetime.fromisoformat(token_data["expires_at"])
    if datetime.datetime.utcnow() > expires_at:
        raise HTTPException(status_code=400, detail="Token expirado.")
    
    return {"valid": True, "email": token_data["email"]}

@app.post("/api/auth/reset-password")
def reset_password(body: ResetPasswordWithTokenRequest, db=Depends(get_db)):
    token_data = db.execute(
        "SELECT * FROM password_reset_tokens WHERE token=%s AND used=0",
        (body.token,)
    ).fetchone()
    
    if not token_data:
        raise HTTPException(status_code=400, detail="Token inválido.")
    
    expires_at = datetime.datetime.fromisoformat(token_data["expires_at"])
    if datetime.datetime.utcnow() > expires_at:
        raise HTTPException(status_code=400, detail="Token expirado.")
    
    email = token_data["email"]
    user = db.execute("SELECT * FROM users WHERE LOWER(email)=%s", (email.lower(),)).fetchone()
    
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    
    db.execute(
        "UPDATE users SET password_hash=%s, password_changed=1 WHERE key=%s",
        (hash_password(body.new_password), user["key"])
    )
    db.execute("UPDATE password_reset_tokens SET used=1 WHERE token=%s", (body.token,))
    db.commit()
    
    log_action(db, user["key"], user["key"], "Reset de Senha", "Usuário redefiniu senha via e-mail")
    return {"ok": True}

# ── USERS ─────────────────────────────────────────────────────────────────────

@app.get("/api/users")
def list_users(user=Depends(get_current_user), db=Depends(get_db)):
        rows = db.execute("SELECT * FROM users WHERE desligado=0 ORDER BY name").fetchall()
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
        if user["access_level"] < 3:
            if body.access_level >= 2:
                raise HTTPException(status_code=403, detail="Apenas Admin Server (nível 3) pode criar usuários com nível 2 ou superior.")
            if body.is_admin or body.is_admin_user:
                raise HTTPException(status_code=403, detail="Apenas Admin Server (nível 3) pode conceder permissões de admin.")
        key = body.key.lower().strip()
        if db.execute("SELECT 1 FROM users WHERE key=%s", (key,)).fetchone():
            raise HTTPException(status_code=400, detail="Usuário já existe.")
        email = (body.email or "").strip().lower()
        if email and db.execute("SELECT 1 FROM users WHERE LOWER(email)=%s", (email,)).fetchone():
            raise HTTPException(status_code=400, detail="Este e-mail já está em uso.")
        # ── Estrutura de cargos: valida vínculos e deriva nomes de exibição ──
        empresa_final = body.empresa_id or ('orcoma' if body.is_orcoma else 'dialogos')
        cargo_nome, dept_nome = "", ""
        if body.cargo_id:
            c_row = db.execute("SELECT nome, empresa_id FROM cargos WHERE id=%s", (body.cargo_id,)).fetchone()
            if not c_row:
                raise HTTPException(status_code=400, detail="Cargo não encontrado.")
            if c_row["empresa_id"] and c_row["empresa_id"] != empresa_final:
                raise HTTPException(status_code=400, detail="Cargo não pertence à empresa selecionada.")
            cargo_nome = c_row["nome"]
        if body.departamento_id:
            d_row = db.execute("SELECT nome FROM departamentos WHERE id=%s", (body.departamento_id,)).fetchone()
            if not d_row:
                raise HTTPException(status_code=400, detail="Departamento não encontrado.")
            dept_nome = d_row["nome"]
        senioridade_id_final = body.senioridade_id or None
        if senioridade_id_final:
            s_ok = db.execute("SELECT 1 FROM senioridades WHERE id=%s AND empresa_id=%s",
                              (senioridade_id_final, empresa_final)).fetchone()
            if not s_ok:
                raise HTTPException(status_code=400, detail="Senioridade inválida para esta empresa.")
        role_final = (body.role or "").strip() or cargo_nome
        dept_final = (body.dept or "").strip() or dept_nome
        db.execute("""INSERT INTO users
            (key, name, initials, role, dept, level, color, access_level,
            is_admin, is_admin_user, is_rh, is_ouvidor, is_diretor, is_leader, nivel_dourado, points,
            password_hash, password_changed, photo_url, hire_date, org_position, is_orcoma,
            cargo_id, senioridade, senioridade_id, departamento_id, empresa_id, email)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (key, body.name, body.initials, role_final, dept_final,
            body.level, body.color, body.access_level,
            1 if body.is_admin else 0, 1 if body.is_admin_user else 0,
            1 if body.is_rh else 0, 1 if body.is_ouvidor else 0,
            1 if body.is_diretor else 0, 1 if body.is_leader else 0,
            1 if body.nivel_dourado else 0,
            body.points, hash_password(body.password), "",
            body.hire_date or "", body.org_position or 'colaborador', 1 if body.is_orcoma else 0,
            body.cargo_id or None, body.senioridade or '',
            senioridade_id_final, body.departamento_id or None,
            body.empresa_id or ('orcoma' if body.is_orcoma else 'dialogos'),
            email)
        )
        db.commit()
        log_action(db, user["key"], key, "Criação de Usuário", f"Criou usuário {body.name}")
        _notify(db, title="👤 Novo colaborador",
                message=f"{user['name']} criou o usuário {body.name} ({body.role})",
                ntype="system", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=key, play_sound=True)
        # ── Gatilho de Onboarding: aplica templates marcados como automático ──
        try:
            hoje = datetime.date.today().isoformat()
            onboards = db.execute(
                "SELECT * FROM pdi_templates WHERE auto_onboarding=1 ORDER BY created_at ASC"
            ).fetchall()
            for tpl in onboards:
                prazo = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
                _criar_pdi_interno(
                    db, user_key=key, titulo=tpl["titulo"], descricao=tpl["descricao"],
                    data_inicio=hoje, data_fim=prazo,
                    blocos=json.loads(tpl["blocos"] or "[]"),
                    created_by=user["key"], template_id=tpl["id"]
                )
                log_action(db, user["key"], key, "Onboarding Automático",
                           f"Aplicou o plano '{tpl['titulo']}' para {body.name}")
                _notify(db, title="🚀 Bem-vindo(a)! Seu onboarding começou",
                        message=f"O plano '{tpl['titulo']}' foi atribuído a você. Acesse Meus Planos de Desenvolvimento.",
                        ntype="system", target_user_key=key,
                        sender_key=user["key"], sender_name=user["name"],
                        reference_id=key, play_sound=True)
            if onboards:
                db.commit()
        except Exception as e:
            logger.warning(f"Falha ao aplicar onboarding automático para {key}: {e}")
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
        # Impedir auto-promoção: usuário não pode alterar próprio access_level
        if user["key"] == target_key and body.access_level != target["access_level"]:
            raise HTTPException(status_code=403, detail="Você não pode alterar seu próprio nível de acesso.")
        # Nível 2 não pode definir access_level >= 2 nem conceder flags de admin
        if user["access_level"] == 2:
            if body.access_level >= 2:
                raise HTTPException(status_code=403, detail="Apenas Admin Server (nível 3) pode definir nível 2 ou superior.")
            if body.is_admin or body.is_admin_user:
                raise HTTPException(status_code=403, detail="Apenas Admin Server (nível 3) pode conceder permissões de admin.")
        # ── Estrutura de cargos: valida vínculos e deriva nomes de exibição ──
        empresa_efetiva = body.empresa_id if body.empresa_id is not None else target.get("empresa_id")
        cargo_nome, dept_nome = "", ""
        if body.cargo_id:
            c_row = db.execute("SELECT nome FROM cargos WHERE id=%s", (body.cargo_id,)).fetchone()
            if not c_row:
                raise HTTPException(status_code=400, detail="Cargo não encontrado.")
            cargo_nome = c_row["nome"]
        if body.departamento_id is not None and body.departamento_id:
            d_row = db.execute("SELECT nome FROM departamentos WHERE id=%s", (body.departamento_id,)).fetchone()
            if not d_row:
                raise HTTPException(status_code=400, detail="Departamento não encontrado.")
            dept_nome = d_row["nome"]
        if body.senioridade_id:
            s_ok = db.execute(
                "SELECT 1 FROM senioridades WHERE id=%s AND empresa_id=%s",
                (body.senioridade_id, empresa_efetiva or 'dialogos')).fetchone()
            if not s_ok:
                raise HTTPException(status_code=400, detail="Senioridade inválida para esta empresa.")
        role_final = (body.role or "").strip() or cargo_nome or (target.get("role") or "")
        dept_final = (body.dept or "").strip() or dept_nome or (target.get("dept") or "")
        set_clause = """UPDATE users SET name=%s, initials=%s, role=%s, dept=%s, level=%s,
            color=%s, access_level=%s, is_admin=%s, is_admin_user=%s, is_rh=%s, is_ouvidor=%s, is_diretor=%s, is_leader=%s, nivel_dourado=%s, points=%s,
            hire_date=%s, org_position=%s, is_orcoma=%s"""
        params = [body.name, body.initials, role_final, dept_final, body.level,
            body.color, body.access_level,
            1 if body.is_admin else 0, 1 if body.is_admin_user else 0,
            1 if body.is_rh else 0, 1 if body.is_ouvidor else 0,
            1 if body.is_diretor else 0, 1 if body.is_leader else 0,
            1 if body.nivel_dourado else 0,
            body.points,
            body.hire_date or "", body.org_position or 'colaborador', 1 if body.is_orcoma else 0]
        if body.cargo_id is not None:
            set_clause += ", cargo_id=%s"
            params.append(body.cargo_id or None)
        if body.senioridade is not None:
            set_clause += ", senioridade=%s"
            params.append(body.senioridade or '')
        if body.senioridade_id is not None:
            set_clause += ", senioridade_id=%s"
            params.append(body.senioridade_id or None)
        if body.departamento_id is not None:
            set_clause += ", departamento_id=%s"
            params.append(body.departamento_id or None)
        if body.empresa_id is not None:
            set_clause += ", empresa_id=%s"
            params.append(body.empresa_id or None)
        if body.email is not None:
            email = (body.email or "").strip().lower()
            if email:
                dup = db.execute("SELECT 1 FROM users WHERE LOWER(email)=%s AND key<>%s", (email, target_key)).fetchone()
                if dup:
                    raise HTTPException(status_code=400, detail="Este e-mail já está em uso.")
            set_clause += ", email=%s"
            params.append(email)
        set_clause += " WHERE key=%s"
        params.append(target_key)
        db.execute(set_clause, params)
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

DESLIGAMENTO_MOTIVOS = [
    "Baixa Produtividade",
    "Redução do Quadro",
    "Reestruturação organizacional",
    "Incompatibilidade cultural",
    "Problemas de conduta",
    "Pedido de demissão",
    "Fim de contrato",
    "Aposentadoria",
    "Relocação geográfica",
    "Conflito interpessoal",
]

@app.post("/api/users/{target_key}/desligar")
def desligar_user(target_key: str, body: DesligarRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if target_key == user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode desligar a si mesmo.")
    if user["access_level"] < 3 and target["access_level"] >= user["access_level"]:
        raise HTTPException(status_code=403, detail="Regra de ouro violada.")
    if target.get("desligado"):
        raise HTTPException(status_code=400, detail="Colaborador já está desligado.")
    motivo = (body.motivo or "").strip()
    if not motivo:
        raise HTTPException(status_code=400, detail="Selecione o motivo do desligamento.")
    if motivo not in DESLIGAMENTO_MOTIVOS:
        raise HTTPException(status_code=400, detail="Motivo de desligamento inválido.")
    obs = (body.obs or "").strip()
    if len(obs) > 6000:
        raise HTTPException(status_code=400, detail="Observações excedem o limite de 6000 caracteres.")
    today = datetime.date.today().isoformat()
    db.execute("UPDATE users SET desligado=1, desligado_data=%s, desligamento_motivo=%s, desligamento_obs=%s WHERE key=%s",
        (today, motivo, obs, target_key))
    db.commit()
    _invalidate_user_cache(target_key)
    log_action(db, user["key"], target_key, "Desligamento de Usuário", f"Desligou {target['name']} — {motivo}")
    return {"ok": True}

@app.get("/api/users/desligados")
def list_users_desligados(user=Depends(require_level(2)), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM users WHERE desligado=1 ORDER BY desligado_data DESC, name").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password_hash", None)
        d.pop("password_changed", None)
        result.append(d)
    return result

@app.post("/api/users/{target_key}/readmitir")
def readmitir_user(target_key: str, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if not target.get("desligado"):
        raise HTTPException(status_code=400, detail="Colaborador não está desligado.")
    db.execute("UPDATE users SET desligado=0, desligado_data='' WHERE key=%s", (target_key,))
    db.commit()
    _invalidate_user_cache(target_key)
    log_action(db, user["key"], target_key, "Readmissão de Usuário", f"Readmitiu {target['name']}")
    return {"ok": True}

# ── CARGOS & ESTRUTURA MULTIEMPRESA: ver rh_estrutura.py ─────────────────────

# ── CARGOS GERAIS ────────────────────────────────────────────────────────────

@app.get("/api/cargos-gerais")
def list_cargos_gerais(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT c.id, c.nome,
               (SELECT COUNT(*) FROM users u WHERE u.role = c.nome AND u.desligado = 0) AS usuarios
        FROM cargos_gerais c
        ORDER BY c.nome ASC
    """).fetchall()
    return [{"id": r["id"], "nome": r["nome"], "usuarios": r["usuarios"] or 0} for r in rows]

@app.post("/api/cargos-gerais")
def create_cargo_geral(body: CargoGeralRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do cargo é obrigatório.")
    cargo_id = re.sub(r'[^a-z0-9]+', '-', nome.lower()).strip('-') or "cargo-geral"
    base = cargo_id
    n = 1
    while db.execute("SELECT 1 FROM cargos_gerais WHERE id=%s", (cargo_id,)).fetchone():
        cargo_id = f"{base}-{n}"
        n += 1
    db.execute("INSERT INTO cargos_gerais (id, nome, created_at) VALUES (%s,%s,%s)",
               (cargo_id, nome, datetime.datetime.utcnow().isoformat()))
    db.commit()
    log_action(db, user["key"], cargo_id, "Criação de Cargo Geral", f"Criou o cargo geral {nome}")
    return {"id": cargo_id, "ok": True}

@app.put("/api/cargos-gerais/{cargo_id}")
def update_cargo_geral(cargo_id: str, body: CargoGeralRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM cargos_gerais WHERE id=%s", (cargo_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cargo geral não encontrado.")
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do cargo é obrigatório.")
    db.execute("UPDATE cargos_gerais SET nome=%s WHERE id=%s", (nome, cargo_id))
    db.commit()
    log_action(db, user["key"], cargo_id, "Atualização de Cargo Geral", f"Atualizou o cargo geral para {nome}")
    return {"ok": True}

@app.delete("/api/cargos-gerais/{cargo_id}")
def delete_cargo_geral(cargo_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM cargos_gerais WHERE id=%s", (cargo_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cargo geral não encontrado.")
    db.execute("DELETE FROM cargos_gerais WHERE id=%s", (cargo_id,))
    db.commit()
    log_action(db, user["key"], cargo_id, "Exclusão de Cargo Geral", f"Excluiu o cargo geral {row['nome']}")
    return {"ok": True}

# ── HISTÓRICO DE CARREIRA ────────────────────────────────────────────────────

def _validate_carreira_date(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Data inválida em {field}. Use o formato AAAA-MM-DD.")
    return value

@app.get("/api/carreira-historico/{user_key}")
def list_carreira_historico(user_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    target = db.execute("SELECT key FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    rows = db.execute(
        "SELECT id, user_key, cargo, start_date, end_date FROM carreira_historico WHERE user_key=%s ORDER BY start_date ASC",
        (user_key,),
    ).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/carreira-historico/{user_key}")
def add_carreira_historico(user_key: str, body: CarreiraHistoricoRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    target = db.execute("SELECT key FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    cargo = body.cargo.strip()
    if not cargo:
        raise HTTPException(status_code=400, detail="Cargo é obrigatório.")
    start_date = _validate_carreira_date(body.start_date, "data de início")
    if not start_date:
        raise HTTPException(status_code=400, detail="Data de início é obrigatória.")
    end_date = _validate_carreira_date(body.end_date, "data de término")
    if end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="A data de término não pode ser anterior à data de início.")
    if body.cargo_id and not db.execute("SELECT 1 FROM cargos WHERE id=%s", (body.cargo_id,)).fetchone():
        raise HTTPException(status_code=400, detail="Cargo informado não existe.")
    if body.senioridade_id and not db.execute("SELECT 1 FROM senioridades WHERE id=%s", (body.senioridade_id,)).fetchone():
        raise HTTPException(status_code=400, detail="Senioridade informada não existe.")
    entry_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO carreira_historico (id, user_key, cargo, start_date, end_date, created_at, cargo_id, senioridade_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (entry_id, user_key, cargo, start_date, end_date, datetime.datetime.utcnow().isoformat(),
         body.cargo_id or None, body.senioridade_id or None),
    )
    log_action(db, user["key"], user_key, "Registro de Histórico de Carreira", f"Registrou {cargo} ({start_date} a {end_date or 'atual'})")
    db.commit()
    return {"id": entry_id, "ok": True}

@app.delete("/api/carreira-historico/{entry_id}")
def delete_carreira_historico(entry_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM carreira_historico WHERE id=%s", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registro não encontrado.")
    db.execute("DELETE FROM carreira_historico WHERE id=%s", (entry_id,))
    log_action(db, user["key"], row["user_key"], "Exclusão de Histórico de Carreira", f"Removeu {row['cargo']} do histórico")
    db.commit()
    return {"ok": True}

# ── EMPRESAS ─────────────────────────────────────────────────────────────────

@app.get("/api/empresas")
def list_empresas(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT e.id, e.nome, e.cnpj, e.socios, e.endereco, e.logo,
               (SELECT COUNT(*) FROM users u WHERE u.empresa_id = e.id AND u.desligado = 0) AS colaboradores
        FROM empresas e
        ORDER BY e.nome ASC
    """).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/empresas")
def create_empresa(body: EmpresaRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome da empresa é obrigatório.")
    empresa_id = re.sub(r'[^a-z0-9]+', '-', nome.lower()).strip('-') or "empresa"
    base = empresa_id
    n = 1
    while db.execute("SELECT 1 FROM empresas WHERE id=%s", (empresa_id,)).fetchone():
        empresa_id = f"{base}-{n}"
        n += 1
    db.execute("""INSERT INTO empresas (id, nome, cnpj, socios, endereco, logo, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (empresa_id, nome, body.cnpj, body.socios, body.endereco, body.logo, datetime.datetime.utcnow().isoformat()))
    # Estrutura-padrão (templates editáveis) para a nova empresa
    seed_estrutura_padrao(db, empresa_id)
    db.commit()
    log_action(db, user["key"], empresa_id, "Criação de Empresa", f"Criou a empresa {nome}")
    return {"id": empresa_id, "ok": True}

@app.put("/api/empresas/{empresa_id}")
def update_empresa(empresa_id: str, body: EmpresaRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM empresas WHERE id=%s", (empresa_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    nome = body.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome da empresa é obrigatório.")
    db.execute("UPDATE empresas SET nome=%s, cnpj=%s, socios=%s, endereco=%s, logo=%s WHERE id=%s",
               (nome, body.cnpj, body.socios, body.endereco, body.logo, empresa_id))
    db.commit()
    log_action(db, user["key"], empresa_id, "Atualização de Empresa", f"Atualizou a empresa {nome}")
    return {"ok": True}

@app.delete("/api/empresas/{empresa_id}")
def delete_empresa(empresa_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM empresas WHERE id=%s", (empresa_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    affected = db.execute("SELECT key FROM users WHERE empresa_id=%s", (empresa_id,)).fetchall()
    db.execute("UPDATE users SET empresa_id=NULL WHERE empresa_id=%s", (empresa_id,))
    db.execute("DELETE FROM empresas WHERE id=%s", (empresa_id,))
    db.commit()
    for u in affected:
        _invalidate_user_cache(u["key"])
    log_action(db, user["key"], empresa_id, "Exclusão de Empresa", f"Excluiu a empresa {row['nome']}")
    return {"ok": True}

@app.post("/api/empresas/{empresa_id}/logo")
def upload_empresa_logo(empresa_id: str, file: UploadFile = File(...), user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM empresas WHERE id=%s", (empresa_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    ext, _ = _validate_upload_file(file)
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato inválido. Use JPG, PNG ou WEBP.")
    try:
        unique_id = str(uuid.uuid4())
        result = cloudinary.uploader.upload(
            file.file,
            folder="dialogos/empresas",
            public_id=f"logo_{empresa_id}_{unique_id}",
            overwrite=False
        )
        url = result["secure_url"]
        db.execute("UPDATE empresas SET logo=%s WHERE id=%s", (url, empresa_id))
        db.commit()
        return {"url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PDIs (Planos de Desenvolvimento Individual) ────────────────────────────────

PDI_TIPOS_BLOCO = {"texto", "pdf", "video"}
PDI_TIPOS_TEMPLATE = {"onboarding", "promocao", "desenvolvimento"}
ALLOWED_PDI_EXTENSIONS = {".pdf", ".mp4", ".mov", ".webm"}
MAX_PDI_FILE_SIZE = 100 * 1024 * 1024  # 100MB (vídeos)

def _is_gestao(user):
    """RH, admins, diretores e liderança (líder/gestor) podem gerir PDIs."""
    return (
        user.get("access_level", 0) >= 2
        or bool(user.get("is_rh"))
        or bool(user.get("is_admin"))
        or bool(user.get("is_admin_user"))
        or bool(user.get("is_diretor"))
        or bool(user.get("is_leader"))
        or user.get("org_position") in ("lider", "gestor")
    )

def _can_manage_pdi(db, user, target_user_key):
    # Gestão pode atribuir/editar/excluir PDIs de qualquer colaborador.
    if _is_gestao(user):
        return True
    # Colaborador comum não cria nem edita PDIs; apenas marca blocos do próprio
    # plano como concluídos via endpoint dedicado (/blocos/{bloco_id}/concluir).
    return False

def _normalize_bloco(b):
    b = dict(b) if isinstance(b, dict) else {"titulo": str(b)}
    tipo = b.get("tipo") if b.get("tipo") in PDI_TIPOS_BLOCO else ("pdf" if b.get("url") else "texto")
    concluido = bool(b.get("concluido"))
    return {
        "id": str(b.get("id") or uuid.uuid4()),
        "tipo": tipo,
        "titulo": b.get("titulo") or "",
        "descricao": b.get("descricao") or "",
        "url": b.get("url") or "",
        "concluido": concluido,
        "concluido_em": (b.get("concluido_em") or "") if concluido else "",
    }

def _normalize_blocos(blocos):
    return [_normalize_bloco(b) for b in (blocos or [])]

def _pdi_progresso(blocos):
    if not blocos:
        return 0
    done = sum(1 for b in blocos if b.get("concluido"))
    return round(done * 100 / len(blocos))

def _pdi_dict(r):
    d = dict(r)
    d["blocos"] = _normalize_blocos(json.loads(d.get("blocos") or "[]"))
    d["progresso"] = _pdi_progresso(d["blocos"])
    hoje = datetime.date.today().isoformat()
    d["vencido"] = bool(d["status"] == "ativo" and d.get("data_fim") and d["data_fim"] < hoje)
    return d

def _get_pdi_or_404(db, pdi_id):
    row = db.execute("SELECT * FROM pdis WHERE id=%s", (pdi_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="PDI não encontrado.")
    return row

def _auto_finalizar_se_completo(db, pdi_id, blocos_json):
    """Finaliza automaticamente o PDI quando todos os blocos estão concluídos."""
    blocos = json.loads(blocos_json)
    if not blocos or any(not b.get("concluido") for b in blocos):
        return False
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE pdis SET status='finalizado', data_conclusao=%s, updated_at=%s WHERE id=%s AND status='ativo'",
        (now[:10], now, pdi_id)
    )
    return True

@app.get("/api/pdis/meus")
def list_meus_pdis(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT p.*, u.name as user_name, u.role as user_role
        FROM pdis p
        LEFT JOIN users u ON p.user_key = u.key
        WHERE p.user_key = %s
        ORDER BY p.created_at DESC
    """, (user["key"],)).fetchall()
    return [_pdi_dict(r) for r in rows]

@app.get("/api/pdis")
def list_pdis(user=Depends(get_current_user), db=Depends(get_db)):
    if not _is_gestao(user):
        rows = db.execute("""
            SELECT p.*, u.name as user_name, u.role as user_role
            FROM pdis p
            LEFT JOIN users u ON p.user_key = u.key
            WHERE p.user_key = %s
            ORDER BY p.created_at DESC
        """, (user["key"],)).fetchall()
    else:
        rows = db.execute("""
            SELECT p.*, u.name as user_name, u.role as user_role
            FROM pdis p
            LEFT JOIN users u ON p.user_key = u.key
            ORDER BY p.created_at DESC
        """).fetchall()
    return [_pdi_dict(r) for r in rows]

def _criar_pdi_interno(db, *, user_key, titulo, descricao, data_inicio, data_fim,
                       blocos, created_by, template_id=None, status="ativo"):
    pdi_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    blocos_norm = _normalize_blocos(blocos)
    db.execute("""
        INSERT INTO pdis (id, user_key, titulo, descricao, data_inicio, data_fim, status, blocos, template_id, created_by, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        pdi_id, user_key, titulo, descricao,
        data_inicio, data_fim, status,
        json.dumps(blocos_norm), template_id, created_by, now, now
    ))
    return pdi_id

@app.post("/api/pdis")
def create_pdi(body: PdiRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_manage_pdi(db, user, body.user_key):
        raise HTTPException(status_code=403, detail="Somente RH e liderança podem atribuir planos de desenvolvimento.")
    target = db.execute("SELECT name FROM users WHERE key=%s", (body.user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário alvo não encontrado.")
    pdi_id = _criar_pdi_interno(
        db, user_key=body.user_key, titulo=body.titulo, descricao=body.descricao,
        data_inicio=body.data_inicio, data_fim=body.data_fim,
        blocos=body.blocos, created_by=user["key"], template_id=body.template_id,
        status=body.status or "ativo"
    )
    log_action(db, user["key"], body.user_key, "Criação de PDI", f"Criou PDI '{body.titulo}' para {body.user_key}")
    _notify(db, title="📈 Novo plano de desenvolvimento",
            message=f"{user['name']} atribuiu o plano '{body.titulo}' a você.",
            ntype="system", target_user_key=body.user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=pdi_id, play_sound=True)
    db.commit()
    return {"id": pdi_id, "ok": True}

@app.put("/api/pdis/{pdi_id}")
def update_pdi(pdi_id: str, body: PdiUpdateRequest, user=Depends(get_current_user), db=Depends(get_db)):
    row = _get_pdi_or_404(db, pdi_id)
    if not _can_manage_pdi(db, user, row["user_key"]):
        raise HTTPException(status_code=403, detail="Sem permissão para editar este PDI.")
    set_clause = "updated_at=%s"
    params = [datetime.datetime.utcnow().isoformat()]
    if body.titulo is not None:
        set_clause += ", titulo=%s"
        params.append(body.titulo)
    if body.descricao is not None:
        set_clause += ", descricao=%s"
        params.append(body.descricao)
    if body.data_inicio is not None:
        set_clause += ", data_inicio=%s"
        params.append(body.data_inicio)
    if body.data_fim is not None:
        set_clause += ", data_fim=%s"
        params.append(body.data_fim)
    if body.status is not None:
        set_clause += ", status=%s"
        params.append(body.status)
    if body.data_conclusao is not None:
        set_clause += ", data_conclusao=%s"
        params.append(body.data_conclusao)
    if body.justificativa_expiracao is not None:
        set_clause += ", justificativa_expiracao=%s"
        params.append(body.justificativa_expiracao)
    if body.blocos is not None:
        set_clause += ", blocos=%s"
        params.append(json.dumps(_normalize_blocos(body.blocos)))
    set_clause += " WHERE id=%s"
    params.append(pdi_id)
    db.execute(f"UPDATE pdis SET {set_clause}", params)
    log_action(db, user["key"], row["user_key"], "Atualização de PDI", f"Atualizou PDI '{row['titulo']}'")
    db.commit()
    return {"ok": True}

@app.delete("/api/pdis/{pdi_id}")
def delete_pdi(pdi_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    row = _get_pdi_or_404(db, pdi_id)
    if not _can_manage_pdi(db, user, row["user_key"]):
        raise HTTPException(status_code=403, detail="Sem permissão para excluir este PDI.")
    db.execute("DELETE FROM pdis WHERE id=%s", (pdi_id,))
    log_action(db, user["key"], row["user_key"], "Exclusão de PDI", f"Excluiu PDI '{row['titulo']}'")
    db.commit()
    return {"ok": True}

# ── Blocos: conclusão individual + progresso ──────────────────────────────────

@app.patch("/api/pdis/{pdi_id}/blocos/{bloco_id}/concluir")
def concluir_bloco_pdi(pdi_id: str, bloco_id: str, body: PdiBlocoConcluirRequest,
                       user=Depends(get_current_user), db=Depends(get_db)):
    row = _get_pdi_or_404(db, pdi_id)
    eh_dono = row["user_key"] == user["key"]
    if not eh_dono and not _is_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão para atualizar este plano.")
    if row["status"] == "expirado":
        raise HTTPException(status_code=400, detail="Este plano está expirado.")
    blocos = _normalize_blocos(json.loads(row["blocos"] or "[]"))
    bloco = next((b for b in blocos if b["id"] == bloco_id), None)
    if not bloco:
        raise HTTPException(status_code=404, detail="Bloco não encontrado neste plano.")
    bloco["concluido"] = bool(body.concluido)
    bloco["concluido_em"] = datetime.datetime.utcnow().isoformat()[:10] if body.concluido else ""
    now = datetime.datetime.utcnow().isoformat()
    db.execute("UPDATE pdis SET blocos=%s, updated_at=%s WHERE id=%s",
               (json.dumps(blocos), now, pdi_id))
    finalizado = _auto_finalizar_se_completo(db, pdi_id, json.dumps(blocos))
    progresso = _pdi_progresso(blocos)
    if finalizado:
        log_action(db, user["key"], row["user_key"], "Conclusão de PDI",
                   f"Plano '{row['titulo']}' concluído 100% por {user['name']}")
        _notify(db, title="🎉 Plano concluído",
                message=f"{user['name']} concluiu 100% do plano '{row['titulo']}'.",
                ntype="system", target_user_key=row["created_by"],
                sender_key=user["key"], sender_name=user["name"],
                reference_id=pdi_id, play_sound=True)
    else:
        log_action(db, user["key"], row["user_key"], "Bloco de PDI",
                   f"{'Concluiu' if body.concluido else 'Reabriu'} bloco '{bloco['titulo']}' em '{row['titulo']}' ({progresso}%)")
    db.commit()
    novo_status = "finalizado" if finalizado else row["status"]
    return {"ok": True, "progresso": progresso, "status": novo_status}

# ── Templates de PDI (Onboarding, Promoção etc.) ───────────────────────────────

def _template_dict(r):
    d = dict(r)
    d["blocos"] = _normalize_blocos(json.loads(d.get("blocos") or "[]"))
    return d

@app.get("/api/pdis-templates")
def list_pdi_templates(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("""
        SELECT t.*, u.name as created_by_name
        FROM pdi_templates t
        LEFT JOIN users u ON t.created_by = u.key
        ORDER BY t.created_at DESC
    """).fetchall()
    return [_template_dict(r) for r in rows]

@app.post("/api/pdis-templates")
def create_pdi_template(body: PdiTemplateRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _is_gestao(user):
        raise HTTPException(status_code=403, detail="Somente RH e liderança podem criar templates de PDI.")
    if body.tipo not in PDI_TIPOS_TEMPLATE:
        raise HTTPException(status_code=400, detail="Tipo inválido. Use: onboarding, promocao ou desenvolvimento.")
    tpl_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    db.execute("""
        INSERT INTO pdi_templates (id, titulo, descricao, tipo, auto_onboarding, blocos, created_by, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (tpl_id, body.titulo, body.descricao, body.tipo,
          1 if body.auto_onboarding else 0,
          json.dumps(_normalize_blocos(body.blocos)), user["key"], now, now))
    if body.auto_onboarding:
        db.execute("UPDATE pdi_templates SET auto_onboarding=0 WHERE tipo=%s AND id != %s AND auto_onboarding=1",
                   (body.tipo, tpl_id))
    log_action(db, user["key"], user["key"], "Criação de Template de PDI", f"Criou template '{body.titulo}' ({body.tipo})")
    db.commit()
    return {"id": tpl_id, "ok": True}

@app.put("/api/pdis-templates/{template_id}")
def update_pdi_template(template_id: str, body: PdiTemplateRequest,
                        user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute("SELECT * FROM pdi_templates WHERE id=%s", (template_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    if not _is_gestao(user):
        raise HTTPException(status_code=403, detail="Somente RH e liderança podem editar templates de PDI.")
    if body.tipo not in PDI_TIPOS_TEMPLATE:
        raise HTTPException(status_code=400, detail="Tipo inválido. Use: onboarding, promocao ou desenvolvimento.")
    now = datetime.datetime.utcnow().isoformat()
    db.execute("""
        UPDATE pdi_templates SET titulo=%s, descricao=%s, tipo=%s, auto_onboarding=%s, blocos=%s, updated_at=%s
        WHERE id=%s
    """, (body.titulo, body.descricao, body.tipo,
          1 if body.auto_onboarding else 0,
          json.dumps(_normalize_blocos(body.blocos)), now, template_id))
    if body.auto_onboarding:
        db.execute("UPDATE pdi_templates SET auto_onboarding=0 WHERE tipo=%s AND id != %s AND auto_onboarding=1",
                   (body.tipo, template_id))
    log_action(db, user["key"], user["key"], "Atualização de Template de PDI", f"Atualizou template '{body.titulo}'")
    db.commit()
    return {"ok": True}

@app.delete("/api/pdis-templates/{template_id}")
def delete_pdi_template(template_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute("SELECT * FROM pdi_templates WHERE id=%s", (template_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    if not _is_gestao(user):
        raise HTTPException(status_code=403, detail="Somente RH e liderança podem excluir templates de PDI.")
    db.execute("DELETE FROM pdi_templates WHERE id=%s", (template_id,))
    log_action(db, user["key"], user["key"], "Exclusão de Template de PDI", f"Excluiu template '{row['titulo']}'")
    db.commit()
    return {"ok": True}

@app.post("/api/pdis-templates/{template_id}/aplicar")
def aplicar_pdi_template(template_id: str, body: PdiTemplateAplicarRequest,
                         user=Depends(get_current_user), db=Depends(get_db)):
    tpl = db.execute("SELECT * FROM pdi_templates WHERE id=%s", (template_id,)).fetchone()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    if not _can_manage_pdi(db, user, body.user_key):
        raise HTTPException(status_code=403, detail="Somente RH e liderança podem atribuir planos de desenvolvimento.")
    target = db.execute("SELECT name FROM users WHERE key=%s", (body.user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário alvo não encontrado.")
    pdi_id = _criar_pdi_interno(
        db, user_key=body.user_key, titulo=tpl["titulo"], descricao=tpl["descricao"],
        data_inicio=body.data_inicio, data_fim=body.data_fim,
        blocos=json.loads(tpl["blocos"] or "[]"),
        created_by=user["key"], template_id=template_id
    )
    log_action(db, user["key"], body.user_key, "Atribuição de PDI (Template)",
               f"Atribuiu o template '{tpl['titulo']}' para {body.user_key}")
    _notify(db, title="📈 Novo plano de desenvolvimento",
            message=f"{user['name']} atribuiu o plano '{tpl['titulo']}' a você.",
            ntype="system", target_user_key=body.user_key,
            sender_key=user["key"], sender_name=user["name"],
            reference_id=pdi_id, play_sound=True)
    db.commit()
    return {"id": pdi_id, "ok": True}

# ── Upload de material (PDF/vídeo) para blocos ─────────────────────────────────

@app.post("/api/pdis/upload-material")
def upload_pdi_material(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not _is_gestao(user):
        raise HTTPException(status_code=403, detail="Somente RH e liderança podem enviar materiais de PDI.")
    _check_upload_rate_limit(user["key"])
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome")
    ext = Path(file.filename).suffix.lower()
    if _is_executable(ext):
        raise HTTPException(status_code=400, detail="Arquivos executáveis não são permitidos")
    if ext not in ALLOWED_PDI_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extensão {ext} não permitida. Use PDF ou vídeo (mp4/mov/webm).")
    if file.size and file.size > MAX_PDI_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Arquivo muito grande (máx 100MB)")
    try:
        unique_name = f"{uuid.uuid4()}{ext}"
        result = cloudinary.uploader.upload(
            file.file,
            folder="dialogos/pdis",
            public_id=unique_name.replace(ext, ""),
            resource_type="auto"
        )
        url = result["secure_url"]
        return {"ok": True, "url": url, "name": file.filename,
                "tipo": "pdf" if ext == ".pdf" else "video"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Certificado de conclusão (download manual) ─────────────────────────────────

@app.get("/api/pdis/{pdi_id}/certificado")
def certificado_pdi(pdi_id: str, user=Depends(get_current_user_from_token), db=Depends(get_db)):
    row = _get_pdi_or_404(db, pdi_id)
    if row["user_key"] != user["key"] and not _is_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão para baixar este certificado.")
    blocos = _normalize_blocos(json.loads(row["blocos"] or "[]"))
    completo = row["status"] == "finalizado" or (bool(blocos) and all(b["concluido"] for b in blocos))
    if not completo:
        raise HTTPException(status_code=400, detail="Certificado disponível apenas após concluir 100% do plano.")
    owner = db.execute("SELECT * FROM users WHERE key=%s", (row["user_key"],)).fetchone()
    nome_colaborador = owner["name"] if owner else row["user_key"]

    from fpdf import FPDF
    from io import BytesIO
    from starlette.responses import Response as StarletteResponse

    pdf = FPDF(orientation="L", format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    font_path = os.path.join(os.path.dirname(__file__), "fonts", "NotoEmoji-Regular.ttf")
    pdf.add_font("NotoEmoji", "", font_path)

    logo_path = os.path.join("..", "frontend", "public", "logo-clinica-fivecon.ico")
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=137, y=14, w=26)

    pdf.set_draw_color(107, 123, 58)
    pdf.set_line_width(1.2)
    pdf.rect(10, 10, 277, 190)

    pdf.ln(24)
    pdf.set_font("NotoEmoji", size=28)
    pdf.cell(0, 16, "Certificado de Conclusão", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)
    pdf.set_font("NotoEmoji", size=13)
    pdf.cell(0, 10, "Certificamos que", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)
    pdf.set_font("NotoEmoji", size=22)
    pdf.cell(0, 12, nome_colaborador, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)
    pdf.set_font("NotoEmoji", size=13)
    pdf.cell(0, 10, "concluiu com êxito o plano de desenvolvimento:", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)
    pdf.set_font("NotoEmoji", size=17)
    pdf.multi_cell(0, 10, row["titulo"], align="C")
    pdf.ln(2)
    pdf.set_font("NotoEmoji", size=11)
    total = len(blocos)
    pdf.cell(0, 7, f"{total} bloco(s) de aprendizagem concluído(s)", new_x="LMARGIN", new_y="NEXT", align="C")
    conclusao = row.get("data_conclusao") or datetime.date.today().isoformat()
    periodo = f"Período: {row['data_inicio']} a {conclusao}"
    pdf.cell(0, 7, periodo, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)
    pdf.set_font("NotoEmoji", size=10)
    pdf.cell(0, 7, "Clínica Diálogos - Plataforma de Gestão de Pessoas", new_x="LMARGIN", new_y="NEXT", align="C")
    codigo = f"Código de verificação: {pdi_id}"
    pdf.cell(0, 6, codigo, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, f"Emitido em: {datetime.datetime.now().strftime('%d/%m/%Y')}", new_x="LMARGIN", new_y="NEXT", align="C")

    buf = BytesIO()
    pdf.output(buf)
    nome_arquivo = f"certificado_{nome_colaborador.replace(' ', '_')}_{datetime.date.today().isoformat()}.pdf"
    return StarletteResponse(
        content=buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'}
    )

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

# ── DISC (Perfis Comportamentais) ────────────────────────────────────────────

DISC_DIMENSOES_VALIDAS = {"analista", "executor", "comunicador", "planejador"}

def _validate_disc(disc: str):
    """Valida a chave do perfil DISC. Retorna a chave canônica ordenada."""
    dims = [d.strip().lower() for d in disc.split("+") if d.strip()]
    if not dims or len(dims) > 4:
        return None
    if len(set(dims)) != len(dims) or not set(dims).issubset(DISC_DIMENSOES_VALIDAS):
        return None
    return "+".join(sorted(dims))

@app.put("/api/users/{target_key}/comportamental")
def set_comportamental(target_key: str, body: ComportamentalRequest,
                       user=Depends(get_current_user), db=Depends(get_db)):
    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if user["key"] != target_key and user["access_level"] < 2:
        raise HTTPException(status_code=403, detail="Sem permissão.")
    disc = (body.disc or "").strip()
    if disc:
        canonical = _validate_disc(disc)
        if not canonical:
            raise HTTPException(status_code=400, detail="Perfil comportamental inválido.")
    else:
        canonical = ""
    db.execute("UPDATE users SET disc=%s WHERE key=%s", (canonical, target_key))
    db.commit()
    _invalidate_user_cache(target_key)
    log_action(db, user["key"], target_key, "Perfil Comportamental",
               f"Definiu perfil DISC: {canonical or '(removido)'}")
    return {"ok": True, "disc": canonical}


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
    total = db.execute("SELECT COUNT(*) FROM posts WHERE feed=%s", (feed,)).fetchone()["count"]
    result = []
    for r in rows:
        d = dict(r)
        d["likes"] = json.loads(d.get("likes") or "[]")
        d["comments"] = json.loads(d.get("comments") or "[]")
        d["reactions"] = json.loads(d.get("reactions") or "{}")
        result.append(d)
    return {"posts": result, "total": total}

@app.post("/api/posts")
def create_post(body: CreatePostRequest, user=Depends(get_current_user), db=Depends(get_db)):
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
        if body.feed == "internal":
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

@app.post("/api/posts/{post_id}/react")
def add_post_reaction(post_id: str, body: ReactPostRequest,
                      user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado.")

    emoji = body.emoji.strip()
    if not emoji:
        raise HTTPException(status_code=400, detail="Emoji inválido.")

    existing = db.execute(
        "SELECT id FROM post_reactions WHERE post_id=%s AND user_key=%s AND emoji=%s",
        (post_id, user["key"], emoji)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Você já reagiu com este emoji.")

    reaction_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO post_reactions (id, post_id, user_key, emoji, created_at) VALUES (%s,%s,%s,%s,%s)",
        (reaction_id, post_id, user["key"], emoji, datetime.datetime.utcnow().isoformat())
    )

    reactions = json.loads(post.get("reactions") or "{}")
    reactions.setdefault(emoji, [])
    if user["key"] not in reactions[emoji]:
        reactions[emoji].append(user["key"])
    db.execute("UPDATE posts SET reactions=%s WHERE id=%s",
               (json.dumps(reactions), post_id))

    if post["author_key"] != user["key"]:
        _notify(db, title=f"{emoji} Reação",
                message=f"{user['name']} reagiu com {emoji} à sua publicação",
                ntype="post", target_user_key=post["author_key"],
                sender_key=user["key"], sender_name=user["name"],
                reference_id=post_id, play_sound=False)

    db.commit()
    ws_emit("update_post", {"id": post_id, "feed": post["feed"], "reactions": reactions}, rooms=[f"feed:{post['feed']}", "all"])
    return {"reactions": reactions}

@app.delete("/api/posts/{post_id}/react")
def remove_post_reaction(post_id: str, body: ReactPostRequest,
                         user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado.")

    emoji = body.emoji.strip()
    if not emoji:
        raise HTTPException(status_code=400, detail="Emoji inválido.")

    existing = db.execute(
        "SELECT id FROM post_reactions WHERE post_id=%s AND user_key=%s AND emoji=%s",
        (post_id, user["key"], emoji)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Reação não encontrada.")

    db.execute("DELETE FROM post_reactions WHERE id=%s", (existing["id"],))

    reactions = json.loads(post.get("reactions") or "{}")
    users_list = reactions.get(emoji, [])
    if user["key"] in users_list:
        users_list.remove(user["key"])
    if not users_list:
        reactions.pop(emoji, None)
    else:
        reactions[emoji] = users_list
    db.execute("UPDATE posts SET reactions=%s WHERE id=%s",
               (json.dumps(reactions), post_id))

    db.commit()
    ws_emit("update_post", {"id": post_id, "feed": post["feed"], "reactions": reactions}, rooms=[f"feed:{post['feed']}", "all"])
    return {"reactions": reactions}

@app.put("/api/posts/{post_id}")
def update_post(post_id: str, body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    post = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not post:
        raise HTTPException(status_code=404, detail="Post não encontrado.")
    if post["author_key"] != user["key"]:
        raise HTTPException(status_code=403, detail="Você não pode editar este post.")

    text = body.get("text")
    if text is not None:
        text = _sanitize_text(text.strip())[:10000]
        db.execute("UPDATE posts SET text=%s WHERE id=%s", (text, post_id))

    db.commit()
    ws_emit("update_post", {"id": post_id, "feed": post["feed"], "text": text}, rooms=[f"feed:{post['feed']}", "all"])
    return {"ok": True, "text": text}

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
    agg = db.execute("""
        SELECT COUNT(*) AS total, COUNT(pv.post_id) AS viewed_count
        FROM posts p
        LEFT JOIN post_views pv ON pv.post_id = p.id AND pv.user_key = %s
        WHERE p.feed = %s
    """, (user["key"], feed)).fetchone()
    total = agg["total"] if agg else 0
    viewed_count = agg["viewed_count"] if agg else 0
    unviewed_count = total - viewed_count
    rows = db.execute("""
        SELECT p.id FROM posts p
        LEFT JOIN post_views pv ON pv.post_id = p.id AND pv.user_key = %s
        WHERE p.feed = %s AND pv.post_id IS NULL
        ORDER BY p.created_at DESC
        LIMIT 50
    """, (user["key"], feed)).fetchall()
    unviewed_ids = [r["id"] for r in rows]
    return {
        "total": total,
        "unviewed_count": unviewed_count,
        "unviewed_ids": unviewed_ids,
    }

# ═════════════════════════════════════════════════════════════════════════════
# COMUNICADOS MODULE (institutional communications)
# ═════════════════════════════════════════════════════════════════════════════

_COMUNICADO_RATE_LIMITS = {}  # user_key -> list of publish timestamps for rate limiting

_comunicados_tables_ready = False
_comunicados_tables_lock = threading.Lock()

def _ensure_comunicados_table(db):
    """Create comunicados tables + indexes once per process. No-op afterwards."""
    global _comunicados_tables_ready
    if _comunicados_tables_ready:
        return
    with _comunicados_tables_lock:
        if _comunicados_tables_ready:
            return
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
        _comunicados_tables_ready = True


def _can_publish_comunicado(user) -> bool:
    role = (user.get("role") or "").lower()
    return bool(
        user.get("is_admin") or user.get("is_admin_user") or
        user.get("is_rh") or user.get("is_diretor") or user.get("is_leader") or
        role in ("diretora", "diretor", "líder", "lider", "admin", "rh", "ceo")
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

@app.get("/api/colleague-feedback")
def list_colleague_feedback(limit: int = 50, offset: int = 0,
                            user=Depends(get_current_user), db=Depends(get_db)):
    # Privados: visíveis apenas para autor e destinatário
    visibility = "(COALESCE(cf.is_private,0) = 0 OR cf.author_key = %s OR cf.target_user_key = %s)"
    rows = db.execute(
        f"""SELECT cf.*,
            u.name AS author_name,
            u.initials AS author_initials,
            u.color   AS author_color,
            u.photo_url AS author_photo
           FROM colleague_feedback cf
           LEFT JOIN users u ON u.key = cf.author_key
           WHERE {visibility}
           ORDER BY cf.created_at DESC LIMIT %s OFFSET %s""",
        (user["key"], user["key"], limit, offset)
    ).fetchall()
    total = db.execute(
        f"SELECT COUNT(*) AS cnt FROM colleague_feedback cf WHERE {visibility}",
        (user["key"], user["key"])
    ).fetchone()["cnt"]
    result = []
    for r in rows:
        entry = dict(r)
        entry["reactions"] = json.loads(entry.get("reactions") or "{}")
        entry["criteria"] = json.loads(entry.get("criteria") or "{}")
        entry["is_private"] = bool(entry.get("is_private"))
        can_delete = user["key"] == entry["author_key"] or user.get("is_admin")
        entry["can_delete"] = can_delete
        result.append(entry)
    return {"items": result, "total": total}

@app.get("/api/colleague-feedback/{target_key}")
def get_colleague_feedback(target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    # Privados: visíveis apenas para autor e destinatário
    visibility = "(COALESCE(cf.is_private,0) = 0 OR cf.author_key = %s OR cf.target_user_key = %s)"
    rows = db.execute(
        f"""SELECT cf.*,
            u.name AS author_name,
            u.initials AS author_initials,
            u.color   AS author_color,
            u.photo_url AS author_photo
           FROM colleague_feedback cf
           LEFT JOIN users u ON u.key = cf.author_key
           WHERE cf.target_user_key=%s AND {visibility}
           ORDER BY cf.created_at DESC LIMIT 50""",
        (target_key, user["key"], user["key"])
    ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        entry["reactions"] = json.loads(entry.get("reactions") or "{}")
        entry["criteria"] = json.loads(entry.get("criteria") or "{}")
        entry["is_private"] = bool(entry.get("is_private"))
        can_delete = user["key"] == entry["author_key"] or user.get("is_admin")
        entry["can_delete"] = can_delete
        result.append(entry)
    return result

@app.post("/api/colleague-feedback")
def create_colleague_feedback(body: dict, user=Depends(get_current_user), db=Depends(get_db)):
    target_key = body.get("target_user_key") or body.get("target_key", "")
    text = body.get("text", "").strip()[:6000]
    is_private = bool(body.get("is_private", False))
    if not text:
        raise HTTPException(status_code=400, detail="Feedback não pode ser vazio.")
    if not target_key:
        raise HTTPException(status_code=400, detail="Destinatário do feedback não informado.")

    criteria_keys = ("responsabilidade", "atendimento", "dominio", "pontualidade", "equipe")
    criteria = {}
    raw_criteria = body.get("criteria")
    if isinstance(raw_criteria, dict):
        for k in criteria_keys:
            v = raw_criteria.get(k)
            if isinstance(v, (int, float)) and 1 <= v <= 5:
                criteria[k] = int(v)
            else:
                raise HTTPException(status_code=400, detail=f"Critério '{k}' deve ter nota de 1 a 5.")

    rating = body.get("rating")
    if criteria:
        rating = round(sum(criteria.values()) / len(criteria_keys) * 2)

    fid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()

    clean_preview = _sanitize_text(text)
    preview = clean_preview[:80] + ("…" if len(clean_preview) > 80 else "")

    is_todos = target_key == "todos" or target_key == "@todos"

    if is_todos:
        if user["key"] == "system":
            raise HTTPException(status_code=400, detail="Operação inválida.")
        # @todos é público por natureza: is_private é ignorado
        db.execute(
            "INSERT INTO colleague_feedback (id, target_user_key, author_key, text, reactions, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
            (fid, "@todos", user["key"], text, "{}", now)
        )
        log_audit(db, user["key"], "colleague_feedback_create", "@todos", f"Feedback para o time de {user['name']}")
        _notify(db, title="💬 Feedback para o time",
                message=f"{user['name']} enviou um feedback: \"{preview}\"",
                ntype="celebration", audience="all",
                sender_key=user["key"], sender_name=user["name"],
                reference_id=fid, play_sound=False)
        _log_atividade(db, "feedback", user["key"],
                       f"{user['name']} enviou um feedback para o time: \"{preview}\"")
    else:
        if user["key"] == target_key:
            raise HTTPException(status_code=400, detail="Você não pode avaliar a si mesmo.")
        trow = db.execute("SELECT name FROM users WHERE key=%s", (target_key,)).fetchone()
        if not trow:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        if rating is None:
            raise HTTPException(status_code=400, detail="Nota do feedback não informada.")
        db.execute(
            "INSERT INTO colleague_feedback (id, target_user_key, author_key, text, rating, criteria, reactions, created_at, is_private) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (fid, target_key, user["key"], text, rating, json.dumps(criteria), "{}", now, 1 if is_private else 0)
        )
        log_audit(db, user["key"], "colleague_feedback_create", target_key,
                  f"Feedback {'privado ' if is_private else ''}de {user['name']} para {trow['name']}")
        _notify(db, title="💬 Feedback recebido",
                message=(f"🔒 {user['name']} enviou um feedback privado: \"{preview}\""
                         if is_private else
                         f"{user['name']} enviou um feedback: \"{preview}\""),
                ntype="feedback", target_user_key=target_key,
                sender_key=user["key"], sender_name=user["name"],
                reference_id=fid, play_sound=False)
        # Feedback privado não aparece no feed público de atividades
        if not is_private:
            _log_atividade(db, "feedback", user["key"],
                           f"{user['name']} enviou um feedback para {trow['name']}: \"{preview}\"")

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
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).isoformat()
    rows = db.execute("""
        SELECT user_key,
               CASE WHEN is_online=1 AND last_activity >= %s THEN 1 ELSE 0 END AS is_online,
               last_seen, last_activity
        FROM presence
    """, (cutoff,)).fetchall()
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

# ── SUGESTÕES DE MELHORIAS ────────────────────────────────────────────────────

SUGESTOES_DEV_KEY = "gabriel"

@app.get("/api/sugestoes")
def get_sugestoes(user=Depends(get_current_user), db=Depends(get_db)):
    is_dev = user["key"] == SUGESTOES_DEV_KEY
    where = "" if is_dev else "WHERE s.author_key=%s"
    params = None if is_dev else (user["key"],)
    rows = db.execute(f"""
        SELECT s.id, s.author_key, s.text, s.is_done, s.done_reason,
               s.status_by_key, s.updated_at, s.created_at,
               u.name AS author_name, u.initials AS author_initials,
               u.color AS author_color, u.photo_url AS author_photo_url
        FROM melhoria_sugestoes s
        LEFT JOIN users u ON u.key = s.author_key
        {where}
        ORDER BY s.created_at ASC
    """, params).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        item["is_done"] = bool(item.get("is_done"))
        item["can_manage"] = user["key"] == SUGESTOES_DEV_KEY
        if not item.get("author_name"):
            item["author_name"] = item.get("author_key") or "Usuário removido"
            item["author_initials"] = "?"
            item["author_color"] = "av-gold"
            item["author_photo_url"] = ""
        result.append(item)
    return result

@app.post("/api/sugestoes")
def create_sugestao(body: SugestaoRequest, user=Depends(get_current_user), db=Depends(get_db)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Escreva sua sugestão antes de enviar.")
    if len(text) > 500:
        raise HTTPException(status_code=422, detail="Sugestão muito longa (máx. 500 caracteres).")
    sid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO melhoria_sugestoes (id, author_key, text, created_at) VALUES (%s,%s,%s,%s)",
        (sid, user["key"], text, now)
    )
    db.commit()
    ws_emit("sugestoes_updated", {"type": "created", "id": sid})
    return {"ok": True, "id": sid}

@app.patch("/api/sugestoes/{sid}/status")
def update_sugestao_status(sid: str, body: SugestaoStatusRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if user["key"] != SUGESTOES_DEV_KEY:
        raise HTTPException(status_code=403, detail="Apenas o desenvolvedor pode atualizar o status.")
    row = db.execute("SELECT * FROM melhoria_sugestoes WHERE id=%s", (sid,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sugestão não encontrada")
    reason = (body.reason or "").strip()
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        "UPDATE melhoria_sugestoes SET is_done=%s, done_reason=%s, status_by_key=%s, updated_at=%s WHERE id=%s",
        (int(body.is_done), reason, user["key"], now, sid)
    )
    log_audit(db, user["key"], "sugestao_status", None,
              f"Status {'feito' if body.is_done else 'pendente'} | motivo: {reason or '-'}")
    if row["author_key"] != user["key"]:
        if body.is_done:
            _notify(db, title="✅ Sua sugestão foi implementada",
                    message=reason or f"{user['name']} marcou sua sugestão como feita",
                    ntype="system", target_user_key=row["author_key"],
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=sid, play_sound=True)
        else:
            _notify(db, title="↩️ Sua sugestão foi avaliada",
                    message=reason or f"{user['name']} marcou sua sugestão como pendente",
                    ntype="system", target_user_key=row["author_key"],
                    sender_key=user["key"], sender_name=user["name"],
                    reference_id=sid, play_sound=True)
    db.commit()
    ws_emit("sugestoes_updated", {"type": "status", "id": sid})
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

_BRT = datetime.timezone(datetime.timedelta(hours=-3))

def _mood_today_record(db, user_key):
    """Retorna o registro de humor do usuário caso já tenha avaliado hoje (fuso BRT)."""
    try:
        row = db.execute(
            "SELECT mood, created_at FROM mood_history WHERE user_key=%s ORDER BY created_at DESC LIMIT 1",
            (user_key,)
        ).fetchone()
        if not row or not row["created_at"]:
            return None
        dt = datetime.datetime.fromisoformat(str(row["created_at"]))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        if dt.astimezone(_BRT).date() == datetime.datetime.now(_BRT).date():
            return row
    except (ValueError, TypeError):
        return None
    return None

def _check_mood_rate_limit(user_key: str):
    hoje = datetime.date.today().isoformat()
    key = f"mood:{user_key}:{hoje}"
    count = _mood_rate.get(key, 0)
    if count >= 1:
        raise HTTPException(status_code=429, detail="Você já registrou seu humor hoje. Volte amanhã!")
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

    if _mood_today_record(db, user["key"]):
        raise HTTPException(status_code=429, detail="Você já registrou seu humor hoje. Volte amanhã!")

    _check_mood_rate_limit(user["key"])

    intensity = body.intensity if body.intensity else None

    db.execute("""INSERT INTO mood_history (id, user_key, mood, intensity, reason, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (str(uuid.uuid4()), user["key"], mood_key, intensity, body.reason or "",
        datetime.datetime.utcnow().isoformat())
    )

    _log_atividade(db, "humor", user["key"],
                   f"{user['name']} respondeu o Termômetro do Humor")

    _notify(db, title="😊 Humor registrado",
            message=f"{user['name']} respondeu o Termômetro do Humor",
            ntype="humor",
            sender_key=user["key"], sender_name=user["name"],
            play_sound=False)

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

@app.get("/api/mood/status")
def get_mood_status(user=Depends(get_current_user), db=Depends(get_db)):
    rec = _mood_today_record(db, user["key"])
    valor = None
    if rec:
        valor = {v: k for k, v in MOOD_VALUES.items()}.get(rec["mood"])
    return {"registered_today": bool(rec), "valor_humor": valor}

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
    if user.get("is_rh") or user.get("is_leader") or user.get("is_diretor"):
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

POP_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".xml": "application/xml",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
}

def _pop_media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return POP_MEDIA_TYPES.get(ext, "application/octet-stream")

def _fetch_pop_bytes(url: str) -> bytes:
    import httpx
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha ao carregar o arquivo original: {str(e)}")

def _pop_file_response(file_id: str, disposition: str, db) -> Response:
    f = db.execute("SELECT * FROM pop_files WHERE id=%s", (file_id,)).fetchone()
    if not f:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    content = _fetch_pop_bytes(f["url"])
    filename = f["name"] or "documento"
    return Response(
        content=content,
        media_type=_pop_media_type(filename),
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}"},
    )

@app.get("/api/pops-files/{file_id}/view")
def view_pop_file(file_id: str, user=Depends(get_current_user_from_token), db=Depends(get_db)):
    return _pop_file_response(file_id, "inline", db)

@app.get("/api/pops-files/{file_id}/download")
def download_pop_file(file_id: str, user=Depends(get_current_user_from_token), db=Depends(get_db)):
    return _pop_file_response(file_id, "attachment", db)

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


# FEEDBACK SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

_feedback_tables_ready = False
_feedback_tables_lock = threading.Lock()

def _ensure_feedback_tables(db):
    """Create feedback tables once per process. No-op afterwards."""
    global _feedback_tables_ready
    if _feedback_tables_ready:
        return
    with _feedback_tables_lock:
        if _feedback_tables_ready:
            return
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
        _feedback_tables_ready = True


def _can_evaluate(user: dict) -> bool:
    """Only RH, admin, admin_user, or ouvidor can create feedback."""
    return bool(user.get('is_admin') or user.get('is_admin_user') or
                user.get('is_rh') or user.get('is_ouvidor'))


@app.get("/api/feedbacks/{target_key}")
def get_feedbacks(target_key: str, user=Depends(get_current_user), db=Depends(get_db), direction: str = 'received'):
    _ensure_feedback_tables(db)
    if direction == 'sent':
        rows = db.execute(
            "SELECT * FROM feedbacks WHERE evaluator_key=%s ORDER BY created_at DESC",
            (target_key,)
        ).fetchall()
    else:
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

@app.get("/api/metricas/reconhecimentos")
def get_metric_reconhecimentos(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM atividades_dialogos WHERE tipo='parabens' AND autor_key=%s",
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

@app.get("/api/metricas/feedbacks-criterias")
def get_metric_feedback_criterias(user=Depends(get_current_user), db=Depends(get_db)):
    criteria_keys = ("responsabilidade", "atendimento", "dominio", "pontualidade", "equipe")
    rows = db.execute(
        "SELECT criteria FROM colleague_feedback WHERE criteria IS NOT NULL AND criteria != '' AND criteria != '{}'"
    ).fetchall()
    sums = {k: 0 for k in criteria_keys}
    counts = {k: 0 for k in criteria_keys}
    for r in rows:
        try:
            c = json.loads(r["criteria"]) if isinstance(r["criteria"], str) else (r["criteria"] or {})
        except Exception:
            continue
        if not isinstance(c, dict):
            continue
        for k in criteria_keys:
            v = c.get(k)
            if isinstance(v, (int, float)) and 1 <= v <= 5:
                sums[k] += v
                counts[k] += 1
    total = sum(1 for k in criteria_keys if counts[k])
    return {
        "criteria": {
            k: (round(sums[k] / counts[k], 1) if counts[k] else None) for k in criteria_keys
        },
        "count": total,
    }

@app.get("/api/metricas/pesquisas")
def get_metric_pesquisas(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM pesquisa_respostas WHERE user_key=%s",
        (user["key"],)
    ).fetchone()
    return {"count": row["cnt"] if row else 0}

@app.get("/api/metricas/colaboradores")
def get_metric_colaboradores(user=Depends(get_current_user), db=Depends(get_db)):
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE desligado=0"
    ).fetchone()
    return {"count": row["cnt"] if row else 0}


# ── PAINEL DO CEO ───────────────────────────────────────────────────────────────

def _is_ceo_or_dev(user) -> bool:
    """Acesso exclusivo: CEO ou o desenvolvedor responsável."""
    if not user:
        return False
    if user.get("key") == SUGESTOES_DEV_KEY:
        return True
    return (user.get("role") or "").strip().lower() == "ceo"


@app.get("/api/ceo/painel")
def ceo_painel(user=Depends(get_current_user), db=Depends(get_db)):
    """Agrega visão geral, vagas em análise, clima da equipe e destaques do mês."""
    if not _is_ceo_or_dev(user):
        raise HTTPException(status_code=403, detail="Painel exclusivo do CEO.")

    hoje = datetime.date.today()
    inicio_mes = hoje.replace(day=1).isoformat()
    inicio_30d = (hoje - datetime.timedelta(days=30)).isoformat()

    # 1. Contadores rápidos
    colaboradores = db.execute(
        "SELECT COUNT(*) as cnt FROM users WHERE COALESCE(desligado,0)=0"
    ).fetchone()["cnt"]

    sugestoes_pendentes = db.execute(
        "SELECT COUNT(*) as cnt FROM melhoria_sugestoes WHERE COALESCE(is_done,0)=0"
    ).fetchone()["cnt"]

    feedbacks_mes = db.execute(
        "SELECT COUNT(*) as cnt FROM feedbacks WHERE created_at >= %s",
        (inicio_mes,)
    ).fetchone()["cnt"]

    vagas_analise = db.execute(
        "SELECT COUNT(*) as cnt FROM vagas WHERE status='em_analise'"
    ).fetchone()["cnt"]

    # 2. Vagas aguardando análise
    vagas_rows = db.execute("""
        SELECT v.*,
               (SELECT COUNT(*) FROM vaga_candidaturas c WHERE c.vaga_id = v.id) AS total_candidaturas
        FROM vagas v WHERE v.status='em_analise' ORDER BY v.created_at ASC
    """).fetchall()

    # 3. Clima/humor da equipe (últimos 30 dias)
    humor_rows = db.execute(
        "SELECT user_key, mood, created_at FROM mood_history WHERE created_at >= %s ORDER BY created_at ASC",
        (inicio_30d + "T00:00:00",)
    ).fetchall()

    por_dia = {}
    distribuicao = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    participantes = set()
    total_registros = 0
    soma_valores = 0

    for r in humor_rows:
        valor = None
        for v, k in MOOD_VALUES.items():
            if r["mood"] == k:
                valor = v
                break
        if valor is None:
            continue
        participantes.add(r["user_key"])
        distribuicao[valor] += 1
        soma_valores += valor
        total_registros += 1
        por_dia.setdefault(r["created_at"][:10], []).append(valor)

    humor_serie = [
        {
            "data": dia,
            "media": round(sum(vals) / len(vals), 2),
            "total": len(vals),
        }
        for dia, vals in sorted(por_dia.items())
    ]

    media_geral = round(soma_valores / total_registros, 2) if total_registros else 0

    # 4. Destaques do mês (top 5)
    mes_ranking = f"{hoje.year}-{str(hoje.month).zfill(2)}"
    rank_rows = db.execute("""
        SELECT mr.user_key, mr.points, mr.position, u.name, u.initials, u.color, u.photo_url
        FROM monthly_ranking mr JOIN users u ON u.key = mr.user_key
        WHERE mr.month=%s ORDER BY mr.position ASC LIMIT 5
    """, (mes_ranking,)).fetchall()

    ranking = []
    if rank_rows:
        for r in rank_rows:
            d = dict(r)
            ranking.append({
                "position": d["position"], "user_key": d["user_key"],
                "name": d["name"], "initials": d["initials"],
                "color": d["color"], "points": d["points"],
                "photo_url": d.get("photo_url") or "",
            })
    else:
        fallback_rows = db.execute(
            "SELECT key, points, name, initials, color, photo_url FROM users "
            "WHERE points > 0 AND COALESCE(desligado,0)=0 ORDER BY points DESC LIMIT 5"
        ).fetchall()
        for idx, r in enumerate(fallback_rows, 1):
            d = dict(r)
            ranking.append({
                "position": idx, "user_key": d["key"], "name": d["name"],
                "initials": d["initials"], "color": d["color"], "points": d["points"],
                "photo_url": d.get("photo_url") or "",
            })

    return {
        "stats": {
            "colaboradores": colaboradores or 0,
            "sugestoes_pendentes": sugestoes_pendentes or 0,
            "feedbacks_mes": feedbacks_mes or 0,
            "vagas_analise": vagas_analise or 0,
        },
        "vagas_pendentes": [_vaga_dict(r) for r in vagas_rows],
        "humor": {
            "media_geral": media_geral,
            "total_registros": total_registros,
            "participantes": len(participantes),
            "distribuicao": {str(k): v for k, v in distribuicao.items()},
            "serie": humor_serie,
        },
        "ranking": ranking,
        "mes_ranking": mes_ranking,
    }


# ── PESQUISAS ───────────────────────────────────────────────────────────────────

def _can_manage_pesquisas(user) -> bool:
    """CEO, RH, Líder, Diretor, Admin ou gestão podem gerir pesquisas."""
    if not user:
        return False
    if user.get("is_admin") or user.get("is_admin_user") or user.get("is_rh") or user.get("is_diretor") or user.get("is_leader"):
        return True
    if int(user.get("access_level", 0) or 0) >= 2:
        return True
    role = (user.get("role") or "").strip().lower()
    if role == "ceo":
        return True
    pos = (user.get("org_position") or "").strip().lower()
    if pos in ("gestor", "supervisor", "lider"):
        return True
    return False

@app.get("/api/pesquisas")
def list_pesquisas(user=Depends(get_current_user), db=Depends(get_db)):
    """Listar pesquisas (para gestão). Exige permissão."""
    if not _can_manage_pesquisas(user):
        raise HTTPException(status_code=403, detail="Sem permissão para gerir pesquisas.")
    rows = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM pesquisa_respostas r WHERE r.pesquisa_id = p.id) as total_respostas
        FROM pesquisas p
        ORDER BY p.created_at DESC
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        result.append(d)
    return result

@app.post("/api/pesquisas")
def criar_pesquisa(body: PesquisaRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_manage_pesquisas(user):
        raise HTTPException(status_code=403, detail="Sem permissão para publicar pesquisas.")
    pid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    if not body.titulo.strip() or not body.pergunta.strip():
        raise HTTPException(status_code=400, detail="Título e pergunta são obrigatórios.")
    db.execute("""
        INSERT INTO pesquisas (id, titulo, pergunta, escala_max, criado_por, criado_por_nome, is_active, created_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s)
    """, (pid, body.titulo.strip(), body.pergunta.strip(), body.escala_max or 10,
          user["key"], user.get("name", ""), now, body.expires_at))
    db.commit()
    log_action(db, user["key"], user["key"], "Publicação de Pesquisa", f"Publicou pesquisa: {body.titulo}")
    return {"id": pid, "message": "Pesquisa publicada."}

@app.get("/api/pesquisas/ativas")
def pesquisas_ativas(user=Depends(get_current_user), db=Depends(get_db)):
    """Pesquisas ativas + se o usuário já respondeu (para o modal)."""
    rows = db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM pesquisa_respostas r WHERE r.pesquisa_id = p.id) AS total_respostas
        FROM pesquisas p
        WHERE p.is_active = 1
        ORDER BY p.created_at DESC
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        resp = db.execute(
            "SELECT * FROM pesquisa_respostas WHERE pesquisa_id=%s AND user_key=%s",
            (d["id"], user["key"])
        ).fetchone()
        d["ja_respondida"] = resp is not None
        d["minha_resposta"] = dict(resp) if resp else None
        result.append(d)
    return result


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
    user_key: str = "",
    user=Depends(get_current_user),
    db=Depends(get_db)
):
    hoje = datetime.date.today().isoformat()
    agora = datetime.datetime.utcnow().isoformat()
    target_key = user_key if (user_key and _is_gestor(user)) else user["key"]

    # Auto-atualizar tarefas em andamento com prazo vencido para atrasadas
    db.execute(
        """UPDATE tarefas SET status = 'atrasada', delayed_at = %s
           WHERE destinatario_id = %s
           AND status = 'andamento'
           AND prazo < %s
           AND concluida = 0""",
        (agora, target_key, hoje)
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
        rows = db.execute(query, (target_key, hoje)).fetchall()
    elif filtro == "amanha":
        amanha = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        query = base_query + " AND t.prazo = %s ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (target_key, amanha)).fetchall()
    elif filtro == "semana":
        fim_semana = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        query = base_query + " AND t.prazo <= %s ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (target_key, fim_semana)).fetchall()
    else:
        query = base_query + " ORDER BY t.prazo ASC, t.created_at DESC"
        rows = db.execute(query, (target_key,)).fetchall()

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
    conditions = []
    params = []

    if _is_gestor(user) and colaborador_filter:
        conditions.append("t.destinatario_id = %s")
        params.append(colaborador_filter)
    else:
        conditions.append("(t.destinatario_id = %s OR t.criado_por = %s)")
        params += [user_key, user_key]

    if status_filter:
        conditions.append("t.status = %s")
        params.append(status_filter)
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
        "user_key": row.get("user_key"),
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
        SELECT a.id, a.nome, a.tipo, a.dia, a.mes, a.departamento,
               COALESCE(NULLIF(a.foto_url, ''), u.photo_url) AS foto_url,
               u.key AS user_key
        FROM aniversarios a
        LEFT JOIN users u ON lower(u.name) = lower(a.nome)
        WHERE a.ativo = true
          AND a.mes = %s
        ORDER BY a.dia ASC
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

_notifications_tables_ready = False
_notifications_tables_lock = threading.Lock()

def _ensure_notifications_table(db):
    """Create notifications table + indexes once per process. No-op afterwards."""
    global _notifications_tables_ready
    if _notifications_tables_ready:
        return
    with _notifications_tables_lock:
        if _notifications_tables_ready:
            return
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
        _notifications_tables_ready = True


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
    sender_photo = None
    if sender_key:
        sender_row = db.execute(
            "SELECT photo_url FROM users WHERE key=%s", (sender_key,)
        ).fetchone()
        if sender_row:
            sender_photo = sender_row["photo_url"]
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
        "sender_photo": sender_photo,
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
        """SELECT n.*,
            u.initials AS actor_initials,
            u.color    AS actor_color,
            u.photo_url AS actor_photo
        FROM notifications n
        LEFT JOIN users u ON u.key = n.sender_key
        WHERE n.target_user_key = %s
            OR n.audience = 'all'
            OR n.audience = %s
        ORDER BY n.created_at DESC
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
            u.color   AS actor_color,
            u.photo_url AS actor_photo
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
                "avatar_url": d.get("actor_photo") or None,
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

    total = db.execute("SELECT COUNT(*) FROM ratimbum_posts").fetchone()["count"]
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
    ).fetchone()["count"]
    reactions_count = db.execute(
        "SELECT COUNT(*) FROM ratimbum_reactions r JOIN ratimbum_posts p ON r.post_id=p.id WHERE p.created_at >= %s AND p.created_at < %s",
        (first_day, next_month)
    ).fetchone()["count"]
    current_month = datetime.date.today().month
    birthdays_count = db.execute(
        "SELECT COUNT(*) FROM aniversarios WHERE ativo=true AND mes=%s",
        (current_month,)
    ).fetchone()["count"]
    unique_authors = db.execute(
        "SELECT COUNT(DISTINCT author_key) FROM ratimbum_posts WHERE created_at >= %s AND created_at < %s AND author_type='user'",
        (first_day, next_month)
    ).fetchone()["count"]
    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()["count"]
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
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).isoformat()
    rows = db.execute("""
        SELECT p.user_key, u.name, u.initials, u.color, u.photo_url, u.role
        FROM presence p
        JOIN users u ON u.key = p.user_key
        WHERE p.is_online = 1 AND p.last_activity >= %s
        ORDER BY u.name ASC
    """, (cutoff,)).fetchall()
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

# ── GESTÃO ────────────────────────────────────────────────────────────────────

def _can_gestao(user: dict) -> bool:
    return bool(
        user.get("is_admin") or user.get("is_admin_user") or
        user.get("access_level", 0) >= 2 or
        user.get("is_rh") or user.get("is_diretor") or user.get("is_leader") or
        user.get("org_position") in ("gestor", "supervisor", "lider")
    )

@app.get("/api/gestao/dashboard")
def gestao_dashboard(user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão para acessar a Gestão.")

    users_rows = db.execute("""
        SELECT key, name, initials, color, photo_url, role, dept, level, points,
               is_admin, is_admin_user, is_rh, is_ouvidor, is_diretor, is_leader,
               is_orcoma, nivel_dourado, org_position, hire_date
        FROM users ORDER BY name
    """).fetchall()

    result = []
    for u in users_rows:
        u_dict = dict(u)

        # Feedbacks recebidos
        fb_recebidos = db.execute(
            "SELECT COUNT(*) as cnt FROM feedbacks WHERE target_user_key=%s",
            (u_dict["key"],)
        ).fetchone()["cnt"]

        # Feedbacks dados (como avaliador)
        fb_dados = db.execute(
            "SELECT COUNT(*) as cnt FROM feedbacks WHERE evaluator_key=%s",
            (u_dict["key"],)
        ).fetchone()["cnt"]

        # Último humor
        ultimo_humor = db.execute(
            "SELECT mood, valor_humor, created_at FROM mood_history WHERE user_key=%s ORDER BY created_at DESC LIMIT 1",
            (u_dict["key"],)
        ).fetchone()

        result.append({
            "key": u_dict["key"],
            "name": u_dict["name"],
            "initials": u_dict["initials"],
            "color": u_dict["color"],
            "photo_url": u_dict.get("photo_url", ""),
            "role": u_dict.get("role", ""),
            "dept": u_dict.get("dept", ""),
            "level": u_dict.get("level", "dourado"),
            "points": u_dict.get("points", 0),
            "is_admin": bool(u_dict.get("is_admin")),
            "is_admin_user": bool(u_dict.get("is_admin_user")),
            "is_rh": bool(u_dict.get("is_rh")),
            "is_ouvidor": bool(u_dict.get("is_ouvidor")),
            "is_diretor": bool(u_dict.get("is_diretor")),
            "is_leader": bool(u_dict.get("is_leader")),
            "is_orcoma": bool(u_dict.get("is_orcoma")),
            "nivel_dourado": bool(u_dict.get("nivel_dourado")),
            "org_position": u_dict.get("org_position", "colaborador"),
            "hire_date": u_dict.get("hire_date", ""),
            "stats": {
                "feedbacks_recebidos": fb_recebidos or 0,
                "feedbacks_dados": fb_dados or 0,
                "ultimo_humor": dict(ultimo_humor) if ultimo_humor else None,
            }
        })

    return result


@app.get("/api/gestao/dashboard/{target_key}")
def gestao_dashboard_usuario(target_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")

    target = db.execute("SELECT * FROM users WHERE key=%s", (target_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    target_dict = dict(target)
    target_dict.pop("password_hash", None)

    hoje = datetime.date.today().isoformat()

    # Feedbacks recebidos
    feedbacks = db.execute(
        "SELECT * FROM feedbacks WHERE target_user_key=%s ORDER BY created_at DESC LIMIT 50",
        (target_key,)
    ).fetchall()

    # Humor (últimos 30 dias)
    humor = db.execute(
        """SELECT * FROM mood_history
           WHERE user_key=%s AND created_at >= %s
           ORDER BY created_at ASC""",
        (target_key, (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat())
    ).fetchall()

    humor_translated = []
    for h in humor:
        hd = dict(h)
        val = None
        for v, k in MOOD_VALUES.items():
            if hd["mood"] == k:
                val = v
                break
        humor_translated.append({
            "data": hd["created_at"][:10] if hd["created_at"] else "",
            "valor": val,
            "label": MOOD_VALUES.get(val, hd["mood"]),
            "emoji": MOOD_EMOJIS.get(val, "?"),
            "intensity": hd.get("intensity"),
            "reason": hd.get("reason", ""),
        })

    # Atividades recentes
    atividades = db.execute(
        "SELECT * FROM atividades_dialogos WHERE autor_key=%s ORDER BY created_at DESC LIMIT 20",
        (target_key,)
    ).fetchall()

    return {
        "user": target_dict,
        "feedbacks": [dict(f) for f in feedbacks],
        "humor": humor_translated,
        "atividades": [dict(a) for a in atividades],
    }


# ── CONTRATAÇÃO ───────────────────────────────────────────────────────────────

ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx"}
ALLOWED_DOC_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_DOC_SIZE = 10 * 1024 * 1024  # 10MB


def _validate_doc_file(file: UploadFile):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo sem nome")
    ext = Path(file.filename).suffix.lower()
    mime = file.content_type or ""
    if ext not in ALLOWED_DOC_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Envie o currículo em PDF, DOC ou DOCX.")
    if mime and mime not in ALLOWED_DOC_MIMES:
        raise HTTPException(status_code=400, detail="Tipo de arquivo inválido.")
    if file.size and file.size > MAX_DOC_SIZE:
        raise HTTPException(status_code=400, detail="Currículo muito grande (máx 10MB).")
    return ext


def _ceo_keys(db) -> list[str]:
    rows = db.execute("""
        SELECT key FROM users
        WHERE COALESCE(desligado, 0) = 0 AND LOWER(TRIM(role)) = 'ceo'
    """).fetchall()
    return [r["key"] for r in rows]


def _vaga_dict(row) -> dict:
    d = dict(row)
    d["total_candidaturas"] = None
    return d


def _vaga_aberta(vaga: dict) -> bool:
    if vaga.get("status") != "aprovada":
        return False
    dl = vaga.get("deadline") or ""
    return (not dl) or (datetime.date.today().isoformat() <= dl)


@app.get("/api/vagas")
def listar_vagas(user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    rows = db.execute("""
        SELECT v.*,
               (SELECT COUNT(*) FROM vaga_candidaturas c WHERE c.vaga_id = v.id) AS total_candidaturas
        FROM vagas v ORDER BY v.created_at DESC
    """).fetchall()
    return [_vaga_dict(r) for r in rows]


@app.post("/api/vagas")
def criar_vaga(body: VagaCreateRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    import uuid as _uuid
    now = datetime.datetime.utcnow().isoformat()
    vaga_id = str(_uuid.uuid4())
    db.execute("""INSERT INTO vagas
        (id, titulo, senioridade, descricao, salario, requisitos, expectativas,
         formacao, palavras_chave, status, motivo_rejeicao, created_by, created_by_name,
         apply_token, deadline, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'em_analise','',%s,%s,'',%s,%s,%s)""",
        (vaga_id, body.titulo.strip(), body.senioridade, body.descricao, body.salario,
         body.requisitos, body.expectativas, body.formacao, body.palavras_chave,
         user["key"], user.get("name", ""), body.deadline or "", now, now))
    for ceo_key in _ceo_keys(db):
        _notify(db, title="Nova vaga para análise",
                message=f'{user.get("name", "RH")} abriu a vaga "{body.titulo}". Aguardando sua aprovação.',
                ntype="vaga", target_user_key=ceo_key, reference_id=vaga_id)
    return {"id": vaga_id, "message": "Vaga enviada para análise do CEO."}


@app.post("/api/vagas/{vaga_id}/review")
def revisar_vaga(vaga_id: str, body: VagaReviewRequest, user=Depends(get_current_user), db=Depends(get_db)):
    me = db.execute("SELECT role FROM users WHERE key=%s", (user["key"],)).fetchone()
    is_ceo = bool(me and (me["role"] or "").strip().lower() == "ceo")
    if user.get("access_level", 0) < 2 and not is_ceo:
        raise HTTPException(status_code=403, detail="Somente o CEO pode analisar vagas.")
    vaga = db.execute("SELECT * FROM vagas WHERE id=%s", (vaga_id,)).fetchone()
    if not vaga:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    if vaga["status"] != "em_analise":
        raise HTTPException(status_code=400, detail="Esta vaga já foi analisada.")

    import secrets as _secrets
    if body.aprovada:
        token = _secrets.token_urlsafe(24)
        db.execute("""UPDATE vagas SET status='aprovada', apply_token=%s, deadline=%s, updated_at=%s WHERE id=%s""",
                   (token, body.deadline or "", datetime.datetime.utcnow().isoformat(), vaga_id))
        _notify(db, title="Vaga aprovada",
                message=f'Sua vaga "{vaga["titulo"]}" foi aprovada pelo CEO. O formulário de candidatura já está disponível.',
                ntype="vaga", target_user_key=vaga["created_by"], reference_id=vaga_id)
        rh_rows = db.execute("SELECT key FROM users WHERE is_rh=1 AND COALESCE(desligado,0)=0").fetchall()
        for r in rh_rows:
            if r["key"] != vaga["created_by"]:
                _notify(db, title="Vaga aprovada",
                        message=f'A vaga "{vaga["titulo"]}" foi aprovada. Divulgue o formulário com os candidatos.',
                        ntype="vaga", target_user_key=r["key"], reference_id=vaga_id)
        return {"message": "Vaga aprovada.", "apply_token": token}
    else:
        if not (body.motivo or "").strip():
            raise HTTPException(status_code=400, detail="Descreva os motivos da reprovação.")
        db.execute("""UPDATE vagas SET status='reprovada', motivo_rejeicao=%s, updated_at=%s WHERE id=%s""",
                   (body.motivo.strip(), datetime.datetime.utcnow().isoformat(), vaga_id))
        _notify(db, title="Vaga reprovada",
                message=f'Sua vaga "{vaga["titulo"]}" foi reprovada. Motivos: {body.motivo.strip()}',
                ntype="vaga", target_user_key=vaga["created_by"], reference_id=vaga_id)
        return {"message": "Vaga reprovada."}


@app.put("/api/vagas/{vaga_id}")
def atualizar_vaga(vaga_id: str, body: VagaUpdateRequest, user=Depends(get_current_user), db=Depends(get_db)):
    vaga = db.execute("SELECT * FROM vagas WHERE id=%s", (vaga_id,)).fetchone()
    if not vaga:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    eh_dono = vaga["created_by"] == user["key"]
    if not (_can_gestao(user) and (eh_dono or user.get("access_level", 0) >= 2)):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    allowed = {"titulo", "senioridade", "descricao", "salario", "requisitos",
               "expectativas", "formacao", "palavras_chave", "deadline"}
    updates, params = [], []
    for k, v in fields.items():
        if k in allowed:
            updates.append(f"{k}=%s"); params.append(v)
        elif k == "status" and v in ("encerrada", "aprovada") and vaga["status"] == "aprovada":
            updates.append("status=%s"); params.append(v)
    if not updates:
        return {"message": "Nada a atualizar."}
    updates.append("updated_at=%s"); params.append(datetime.datetime.utcnow().isoformat())
    params.append(vaga_id)
    db.execute(f"UPDATE vagas SET {', '.join(updates)} WHERE id=%s", tuple(params))
    return {"message": "Vaga atualizada."}


@app.delete("/api/vagas/{vaga_id}")
def excluir_vaga(vaga_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    if user.get("access_level", 0) < 2:
        raise HTTPException(status_code=403, detail="Somente administradores.")
    db.execute("DELETE FROM vaga_candidaturas WHERE vaga_id=%s", (vaga_id,))
    db.execute("DELETE FROM vagas WHERE id=%s", (vaga_id,))
    return {"message": "Vaga excluída."}


@app.get("/api/vagas/{vaga_id}/candidaturas")
def listar_candidaturas(vaga_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    rows = db.execute(
        "SELECT * FROM vaga_candidaturas WHERE vaga_id=%s ORDER BY score DESC NULLS LAST, created_at DESC",
        (vaga_id,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["respostas"] = json.loads(d.get("respostas") or "{}")
            d["disc"] = json.loads(d.get("disc") or "{}")
            d["score_breakdown"] = json.loads(d.get("score_breakdown") or "{}")
        except Exception:
            d["respostas"], d["disc"], d["score_breakdown"] = {}, {}, {}
        result.append(d)
    return result


@app.post("/api/candidaturas/{cand_id}/status")
def status_candidatura(cand_id: str, body: CandidaturaStatusRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    if body.status not in ("recebido", "aprovado", "reprovado", "contratado"):
        raise HTTPException(status_code=400, detail="Status inválido.")
    row = db.execute("SELECT id FROM vaga_candidaturas WHERE id=%s", (cand_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Candidatura não encontrada.")
    db.execute("UPDATE vaga_candidaturas SET status=%s WHERE id=%s", (body.status, cand_id))
    return {"message": "Candidato atualizado."}


@app.post("/api/vagas/{vaga_id}/avaliar")
def avaliar_candidaturas(vaga_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    """Executa a análise IA dos currículos da vaga e grava o % de aderência."""
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    from resume_scoring import extract_resume_text, score_candidato
    import urllib.request as _urlreq

    vaga = db.execute("SELECT * FROM vagas WHERE id=%s", (vaga_id,)).fetchone()
    if not vaga:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")
    vaga_d = dict(vaga)
    cands = db.execute(
        "SELECT * FROM vaga_candidaturas WHERE vaga_id=%s", (vaga_id,)).fetchall()

    avaliados = 0
    for c in cands:
        c_d = dict(c)
        texto = ""
        url = c_d.get("curriculo_url") or ""
        if url:
            try:
                full = url if url.startswith("http") else f"https://res.cloudinary/{url}"
                with _urlreq.urlopen(full, timeout=20) as resp:
                    texto = extract_resume_text(resp.read(), c_d.get("curriculo_nome") or "")
            except Exception:
                texto = ""
        respostas_str = json.dumps(c_d.get("respostas"), ensure_ascii=False) if c_d.get("respostas") else ""
        resultado = score_candidato(vaga_d, texto, respostas_str)
        db.execute("""UPDATE vaga_candidaturas
                      SET score=%s, score_breakdown=%s, status=CASE WHEN status='recebido' THEN 'avaliado' ELSE status END
                      WHERE id=%s""",
                   (resultado["score"], json.dumps(resultado["breakdown"], ensure_ascii=False), c_d["id"]))
        avaliados += 1

    return {"message": f"Análise concluída: {avaliados} candidato(s) avaliado(s).", "avaliados": avaliados}


# ── Período de experiência ────────────────────────────────────────────────────

EXPERIENCIA_DIAS = 90


@app.get("/api/experiencia")
def listar_experiencia(user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    hoje = datetime.date.today()
    rows = db.execute("""
        SELECT key, name, initials, color, photo_url, role, dept, hire_date
        FROM users
        WHERE COALESCE(desligado, 0) = 0 AND hire_date IS NOT NULL AND hire_date <> ''
    """).fetchall()

    registros = {}
    for r in db.execute("SELECT * FROM experiencia_registros").fetchall():
        registros[r["user_key"]] = dict(r)

    result = []
    for u in rows:
        u_d = dict(u)
        try:
            inicio = datetime.date.fromisoformat((u_d.get("hire_date") or "")[:10])
        except Exception:
            continue
        fim = inicio + datetime.timedelta(days=EXPERIENCIA_DIAS)
        dias_restantes = (fim - hoje).days
        reg = registros.get(u_d["key"])
        # Exibe quem está no período ou saiu dele há menos de 45 dias sem registro
        if dias_restantes < -45 and (not reg or reg.get("resultado")):
            continue
        result.append({
            **{k: u_d.get(k, "") for k in ("key", "name", "initials", "color", "photo_url", "role", "dept")},
            "hire_date": u_d.get("hire_date", ""),
            "inicio": inicio.isoformat(),
            "fim_previsto": fim.isoformat(),
            "dias_restantes": dias_restantes,
            "registro": reg,
        })
    result.sort(key=lambda x: x["dias_restantes"])
    return result


@app.post("/api/experiencia/{user_key}")
def registrar_experiencia(user_key: str, body: ExperienciaRegistroRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _can_gestao(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    if body.resultado and body.resultado not in ("efetivado", "prorrogado", "desligado"):
        raise HTTPException(status_code=400, detail="Resultado inválido.")
    target = db.execute("SELECT hire_date, name FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    agora = datetime.datetime.utcnow().isoformat()
    inicio = (target["hire_date"] or "")[:10]
    fim = ""
    if inicio:
        try:
            fim = (datetime.date.fromisoformat(inicio) + datetime.timedelta(days=EXPERIENCIA_DIAS)).isoformat()
        except Exception:
            pass
    db.execute("""
        INSERT INTO experiencia_registros (user_key, start_date, end_date, resultado, notas, updated_by, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (user_key) DO UPDATE SET
            resultado=EXCLUDED.resultado, notas=EXCLUDED.notas,
            updated_by=EXCLUDED.updated_by, updated_at=EXCLUDED.updated_at
    """, (user_key, inicio, fim, body.resultado, body.notas, user.get("name", ""), agora))
    return {"message": "Registro salvo."}


# ── CONTRATAÇÃO · Área pública do candidato ──────────────────────────────────

@app.get("/api/public/vagas/{token}")
def public_vaga(token: str, request: Request, db=Depends(get_db)):
    row = db.execute("SELECT * FROM vagas WHERE apply_token=%s", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Inscrição indisponível.")
    vaga = dict(row)
    if not _vaga_aberta(vaga):
        raise HTTPException(status_code=400, detail="O período de inscrições para esta vaga está encerrado.")
    ip = request.client.host if request.client else "?"
    _check_upload_rate_limit(f"pubview:{ip}")
    return {
        "titulo": vaga["titulo"],
        "senioridade": vaga["senioridade"],
        "descricao": vaga["descricao"],
        "salario": vaga["salario"],
        "requisitos": vaga["requisitos"],
        "expectativas": vaga["expectativas"],
        "formacao": vaga["formacao"],
        "deadline": vaga["deadline"],
    }


@app.post("/api/public/vagas/{token}/candidatura")
def public_candidatar(
    token: str,
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(""),
    respostas: str = Form("{}"),
    disc_most: str = Form(""),
    disc_least: str = Form(""),
    curriculo: UploadFile = File(None),
    db=Depends(get_db),
):
    row = db.execute("SELECT * FROM vagas WHERE apply_token=%s", (token,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Inscrição indisponível.")
    vaga = dict(row)
    if not _vaga_aberta(vaga):
        raise HTTPException(status_code=400, detail="O período de inscrições está encerrado.")

    ip = request.client.host if request.client else "?"
    _check_upload_rate_limit(f"public:{ip}")

    nome = nome.strip()
    email_norm = email.strip().lower()
    if len(nome) < 3:
        raise HTTPException(status_code=400, detail="Informe seu nome completo.")
    if "@" not in email_norm or "." not in email_norm:
        raise HTTPException(status_code=400, detail="Informe um e-mail válido.")

    dup = db.execute(
        "SELECT id FROM vaga_candidaturas WHERE vaga_id=%s AND email=%s",
        (vaga["id"], email_norm)).fetchone()
    if dup:
        raise HTTPException(status_code=409, detail="Este e-mail já se inscreveu nesta vaga.")

    # DISC
    def _parse_idx(s):
        out = []
        for p in (s or "").split(","):
            p = p.strip()
            if p.isdigit() and 0 <= int(p) <= 3:
                out.append(int(p))
        return out
    from resume_scoring import compute_disc
    disc_result = compute_disc(_parse_idx(disc_most), _parse_idx(disc_least))

    try:
        respostas_obj = json.loads(respostas or "{}")
    except Exception:
        respostas_obj = {}

    curriculo_url, curriculo_nome = "", ""
    if curriculo and curriculo.filename:
        ext = _validate_doc_file(curriculo)
        data = curriculo.file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Arquivo de currículo vazio.")
        result = cloudinary.uploader.upload(
            io.BytesIO(data),
            resource_type="raw",
            folder="dialogos/curriculos",
            public_id=f"{vaga['id']}_{email_norm.replace('@','_')}_{int(datetime.datetime.utcnow().timestamp())}{ext}",
        )
        curriculo_url = result.get("secure_url", "")
        curriculo_nome = curriculo.filename

    import uuid as _uuid
    cand_id = str(_uuid.uuid4())
    db.execute("""INSERT INTO vaga_candidaturas
        (id, vaga_id, nome, email, telefone, respostas, disc,
         curriculo_url, curriculo_nome, score, score_breakdown, status, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,'{}','recebido',%s)""",
        (cand_id, vaga["id"], nome, email_norm, telefone.strip(),
         json.dumps(respostas_obj, ensure_ascii=False),
         json.dumps(disc_result, ensure_ascii=False),
         curriculo_url, curriculo_nome,
         datetime.datetime.utcnow().isoformat()))

    _notify(db, title="Nova candidatura recebida",
            message=f'"{nome}" se inscreveu na vaga "{vaga["titulo"]}".',
            ntype="vaga", target_user_key=vaga["created_by"], reference_id=vaga["id"])

    return {"message": "Candidatura enviada com sucesso! Boa sorte.", "perfil_disc": disc_result.get("perfil", "")}


CANDIDATURA_HTML = Path(__file__).parent / "static" / "candidatura.html"


@app.get("/candidatura/{token}", include_in_schema=False)
def pagina_candidatura(token: str):
    if not CANDIDATURA_HTML.exists():
        raise HTTPException(status_code=500, detail="Página não encontrada.")
    return FileResponse(CANDIDATURA_HTML, media_type="text/html")


@app.get("/clinica-dialogos.png", include_in_schema=False)
def logo_publico():
    p = Path(__file__).parent / "static" / "clinica-dialogos.png"
    if not p.exists():
        raise HTTPException(status_code=404)
    return FileResponse(p, media_type="image/png")


# Expose a unified ASGI app (FastAPI + Socket.IO)
app = socketio.ASGIApp(sio, app)
