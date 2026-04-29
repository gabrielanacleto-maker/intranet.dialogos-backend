from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import sqlite3, os, uuid, shutil, datetime, hashlib, json
from pathlib import Path
from models import *
from database import get_db, init_db
from auth import create_token, verify_token, hash_password, check_password
import sqlite3
import cloudinary
import cloudinary.uploader

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

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

@app.get("/users")
def get_users():
    from database import get_db

    conn = get_db()  # 👈 usa o que você já importou
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users")

    users = cursor.fetchall()
    conn.close()

    return [dict(u) for u in users]



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173", 
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:3000",
        "http://localhost:*",  # ✅ Fix CORS wildcard dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex="http://localhost:\\d+",  # ✅ Regex localhost any port
)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

security = HTTPBearer(auto_error=False)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Token ausente")
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")
    db = next(get_db())
    # ✅ Fix: list() garante proper fetch
    user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
    if not user_row:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    user = dict(user_row)
    return user

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

def log_action(db, actor_key: str, target_key: str, action_type: str, details: str = ""):
    db.execute(
        "INSERT INTO security_logs (id, actor_key, target_key, action_type, details, created_at) VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), actor_key, target_key, action_type, details, datetime.datetime.utcnow().isoformat())
    )
    db.commit()

def extract_room_id(channel_value: str | None):
    if not channel_value:
        return None
    if channel_value.startswith("sala_"):
        return channel_value[5:]
    return None

def can_access_social_room(db, room_id: str, user):
    room = db.execute("SELECT * FROM social_rooms WHERE id=%s", (room_id,)).fetchone()
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
    ).fetchone()
    return bool(member), room_dict

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login")
def login(body: LoginRequest, db=Depends(get_db)):
    user = db.execute("SELECT * FROM users WHERE key=%s", (body.key.lower(),)).fetchone()
    if not user or not check_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
    token = create_token({"sub": user["key"], "level": user["access_level"]})
    return {
        "token": token,
        "must_change_password": not user["password_changed"],
        "user": {
            "key": user["key"], "name": user["name"], "initials": user["initials"],
            "role": user["role"], "dept": user["dept"], "level": user["level"],
            "color": user["color"], "access_level": user["access_level"],
            "is_admin": user["is_admin"], "is_admin_user": user["is_admin_user"],
            "is_rh": user["is_rh"], "is_ouvidor": user["is_ouvidor"],
            "points": user["points"], "photo_url": user["photo_url"],
        }
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
        result.append(d)
    return result

@app.post("/api/users")
def create_user(body: CreateUserRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    key = body.key.lower().strip()
    if db.execute("SELECT 1 FROM users WHERE key=%s", (key,)).fetchone():
        raise HTTPException(status_code=400, detail="Usuário já existe.")
    db.execute("""INSERT INTO users
        (key, name, initials, role, dept, level, color, access_level,
         is_admin, is_admin_user, is_rh, is_ouvidor, points,
         password_hash, password_changed, photo_url)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
        (key, body.name, body.initials, body.role, body.dept,
         body.level, body.color, body.access_level,
         1 if body.is_admin else 0, 1 if body.is_admin_user else 0,
         1 if body.is_rh else 0, 1 if body.is_ouvidor else 0,
         body.points, hash_password(body.password), "")
    )
    db.commit()
    log_action(db, user["key"], key, "Criação de Usuário", f"Criou usuário {body.name}")
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
         color=%s, access_level=%s, is_admin=%s, is_admin_user=%s, is_rh=%s, is_ouvidor=%s, points=%s
         WHERE key=%s""",
        (body.name, body.initials, body.role, body.dept, body.level,
         body.color, body.access_level,
         1 if body.is_admin else 0, 1 if body.is_admin_user else 0,
         1 if body.is_rh else 0, 1 if body.is_ouvidor else 0,
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
    if user["access_level"] == 2 and target["access_level"] >= 2:
        raise HTTPException(status_code=403, detail="Regra de ouro violada.")
    db.execute("DELETE FROM users WHERE key=%s", (target_key,))
    db.commit()
    log_action(db, user["key"], target_key, "Exclusão de Usuário", f"Removeu {target['name']}")
    return {"ok": True}

@app.post("/api/users/me/photo")
def upload_photo(file: UploadFile = File(...), user=Depends(get_current_user), db=Depends(get_db)):
    ext = Path(file.filename or "foto.jpg").suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
        raise HTTPException(status_code=400, detail="Formato invalido. Use JPG, PNG ou WEBP.")
    
    result = cloudinary.uploader.upload(
        file.file,
        folder="dialogos/fotos",
        public_id=f"photo_{user['key']}",
        overwrite=True
    )
    url = result["secure_url"]
    
    db.execute("UPDATE users SET photo_url=%s WHERE key=%s", (url, user["key"]))
    db.commit()
    return {"url": url}

# ── SECURITY LOGS ─────────────────────────────────────────────────────────────

@app.get("/api/security-logs")
def get_logs(user=Depends(require_level(2)), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM security_logs ORDER BY created_at DESC LIMIT 200").fetchall()
    return [dict(r) for r in rows]

# ── POSTS ─────────────────────────────────────────────────────────────────────

@app.get("/api/posts")
def get_posts(feed: str = "feed", user=Depends(get_current_user), db=Depends(get_db)):
    social_room_id = extract_room_id(feed)
    if social_room_id:
        allowed, _ = can_access_social_room(db, social_room_id, user)
        if not allowed:
            raise HTTPException(status_code=403, detail="Sem acesso a esta sala.")
    rows = db.execute(
        "SELECT * FROM posts WHERE feed=%s ORDER BY pinned DESC, created_at DESC", (feed,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["likes"] = json.loads(d.get("likes") or "[]")
        d["comments"] = json.loads(d.get("comments") or "[]")
        result.append(d)
    return result

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
        post_id = str(uuid.uuid4())
        db.execute("""INSERT INTO posts
    (id, feed, author_key, author_name, author_initials, author_color, author_photo_url,
     text, image_url, embed_url, access_level, comunicado_tipo, pinned, likes, comments, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    (
        post_id,
        body.feed,
        user["key"],
        user["name"],
        user["initials"],
        user["color"],
        user.get("photo_url", ""),
        body.text,
        body.image_url or "",
        body.embed_url or "",
        body.access_level,
        body.comunicado_tipo,
        0,
        '[]',
        '[]',
        datetime.datetime.utcnow().isoformat()
    )
)

        
        db.commit()
        return {"ok": True, "id": post_id}
    except Exception as e:
        print(f"POST error: {e}")  # Backend log
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/posts/upload-image")
def upload_post_image(file: UploadFile = File(...), user=Depends(get_current_user)):
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Imagem muito grande (máx 10MB)")
    ext = Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail="Formato inválido")
    fname = f"post_{uuid.uuid4().hex[:12]}{ext}"
    path = UPLOAD_DIR / fname
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/{fname}"}

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
    comments.append({
        "id": str(uuid.uuid4())[:8],
        "author_key": user["key"],
        "author_name": user["name"],
        "author_initials": user["initials"],
        "author_color": user.get("color", "av-gold"),
        "author_photo_url": user.get("photo_url", ""),
        "text": body.text,
        "created_at": datetime.datetime.utcnow().isoformat()
    })
    db.execute("UPDATE posts SET comments=%s WHERE id=%s", (json.dumps(comments), post_id))
    db.commit()
    return {"comments": comments}

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
        VALUES (?,?,?,?,?,?,?)""",
        (item_id, body.tag, body.title, body.subtitle, body.content,
         body.image_url or "", datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": item_id}

@app.post("/api/mural/upload-image")
def upload_mural_image(file: UploadFile = File(...), user=Depends(get_current_user)):
    can_post = (user["is_admin"] or user["is_admin_user"] or user["is_rh"] or
                user["level"] in ["platina", "diamante"])
    if not can_post:
        raise HTTPException(status_code=403)
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Imagem muito grande (máx 10MB)")
    ext = Path(file.filename).suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
        raise HTTPException(status_code=400, detail="Formato inválido")
    fname = f"mural_{uuid.uuid4().hex[:12]}{ext}"
    path = UPLOAD_DIR / fname
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"url": f"/uploads/{fname}"}

@app.delete("/api/mural/{item_id}")
def delete_mural(item_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    db.execute("DELETE FROM mural_items WHERE id=%s", (item_id,))
    db.commit()
    return {"ok": True}

# ── FOLDERS & FILES ───────────────────────────────────────────────────────────

@app.get("/api/folders")
def get_folders(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM folders ORDER BY name").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/folders")
def create_folder(body: FolderRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    fid = str(uuid.uuid4())
    db.execute("INSERT INTO folders (id, name, icon, level, drive_link) VALUES (?,?,?,?,?)",
               (fid, body.name, body.icon, body.level, body.drive_link or ""))
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
    if file.size and file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (máx 50MB)")
    fname = f"doc_{uuid.uuid4().hex[:12]}_{file.filename}"
    path = UPLOAD_DIR / fname
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_id = str(uuid.uuid4())
    db.execute("""INSERT INTO folder_files (id, folder_id, name, url, size, mime_type, uploaded_by, created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (file_id, folder_id, file.filename, f"/uploads/{fname}",
         os.path.getsize(path), file.content_type or "",
         user["name"], datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "url": f"/uploads/{fname}"}

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
        VALUES (?,?,?,?,?,?,?,?,?)""",
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
    db.commit()
    return {"ok": True, "id": mid}

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
        ).fetchone()[0]
        room["members_count"] = db.execute(
            "SELECT COUNT(*) FROM social_room_members WHERE room_id=%s",
            (room["id"],)
        ).fetchone()[0]
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
        VALUES (?,?,?,?,?,?)""",
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
    db.execute("""INSERT INTO social_room_members (id, room_id, user_key, added_by, created_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT DO NOTHING""",
        (str(uuid.uuid4()), room_id, k, user["key"], datetime.datetime.utcnow().isoformat())
    )
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
    if file.size and file.size > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (máx 50MB)")

    fname = f"sala_{room_id}_{uuid.uuid4().hex[:10]}_{file.filename}"
    path = UPLOAD_DIR / fname
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_id = str(uuid.uuid4())
    db.execute("""INSERT INTO social_room_files (id, room_id, name, url, size, mime_type, uploaded_by, created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
        (
            file_id,
            room_id,
            file.filename,
            f"/uploads/{fname}",
            os.path.getsize(path),
            file.content_type or "",
            user["name"],
            datetime.datetime.utcnow().isoformat()
        )
    )
    db.commit()
    return {"ok": True, "id": file_id, "url": f"/uploads/{fname}"}

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
    if user["is_ouvidor"] or user["is_admin"] or user["is_admin_user"]:
        rows = db.execute("SELECT * FROM ouvidoria ORDER BY created_at DESC").fetchall()
    else:
        rows = db.execute("SELECT * FROM ouvidoria WHERE author_key=%s ORDER BY created_at DESC",
                          (user["key"],)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/ouvidoria")
def create_ouvidoria(body: OuvidoriaRequest, user=Depends(get_current_user), db=Depends(get_db)):
    oid = str(uuid.uuid4())
    db.execute("""INSERT INTO ouvidoria (id, author_key, author_name, category, text, status, created_at)
        VALUES (?,?,?,?,?,'aberta',?)""",
        (oid, user["key"], user["name"], body.category, body.text,
         datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": oid}

@app.put("/api/ouvidoria/{oid}/status")
def update_ouvidoria_status(oid: str, body: OuvidoriaStatusRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    db.execute("UPDATE ouvidoria SET status=%s WHERE id=%s", (body.status, oid))
    db.commit()
    return {"ok": True}

@app.post("/api/ouvidoria/{oid}/respond")
def respond_ouvidoria(oid: str, body: OuvidoriaResponseRequest, user=Depends(require_level(2)), db=Depends(get_db)):
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
    db.commit()
    return {"ok": True}

# ── RANKING ───────────────────────────────────────────────────────────────────

@app.get("/api/ranking")
def get_ranking(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT key, name, initials, color, level, points FROM users ORDER BY points DESC").fetchall()
    return [dict(r) for r in rows]

@app.put("/api/users/{target_key}/points")
def update_points(target_key: str, body: PointsRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    db.execute("UPDATE users SET points=%s WHERE key=%s", (body.points, target_key))
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
            VALUES (?,?,?,?,?)""",
            (org_id, entry.user_key, entry.parent_key or "", entry.position_order, entry.org_tier)
        )
    db.commit()
    return {"ok": True}

# ── MOOD ──────────────────────────────────────────────────────────────────────

@app.post("/api/mood")
def save_mood(body: MoodRequest, user=Depends(get_current_user), db=Depends(get_db)):
    db.execute("""INSERT INTO mood_history (id, user_key, mood, intensity, reason, created_at)
        VALUES (?,?,?,?,?,?)""",
        (str(uuid.uuid4()), user["key"], body.mood, body.intensity, body.reason or "",
         datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True}

@app.get("/api/mood/history")
def get_mood_history(user=Depends(get_current_user), db=Depends(get_db)):
    rows = db.execute("SELECT * FROM mood_history WHERE user_key=%s ORDER BY created_at DESC LIMIT 30",
                      (user["key"],)).fetchall()
    return [dict(r) for r in rows]

# ── PRICE DOCTORS (Tabela de Preços) ──────────────────────────────────────────

@app.get("/api/price-doctors")
def get_price_doctors(folder_id: str, db=Depends(get_db)):
    rows = db.execute("SELECT * FROM price_doctors WHERE folder_id=%s ORDER BY position_order ASC",
                      (folder_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/price-doctors")
def create_price_doctor(body: PriceDoctorRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    doctor_id = str(uuid.uuid4())
    db.execute("""INSERT INTO price_doctors (id, folder_id, name, specialty, crm, rqe, position_order, created_at)
        VALUES (?,?,?,?,?,?,?,?)""",
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
def get_price_procedures(doctor_id: str, db=Depends(get_db)):
    rows = db.execute("SELECT * FROM price_procedures WHERE doctor_id=%s ORDER BY position_order ASC",
                      (doctor_id,)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/price-procedures")
def create_price_procedure(body: PriceProcedureRequest, user=Depends(require_level(1)), db=Depends(get_db)):
    proc_id = str(uuid.uuid4())
    db.execute("""INSERT INTO price_procedures 
        (id, doctor_id, name, value_cash, value_card_pix, value_bradesco, value_brv, value_prefeitura, position_order, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
def get_calendar_events(db=Depends(get_db)):
    rows = db.execute("SELECT * FROM calendar_events ORDER BY start_date ASC").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/calendar")
def create_calendar_event(body: CalendarEventRequest, user=Depends(get_current_user), db=Depends(get_db)):
    event_id = str(uuid.uuid4())
    db.execute("""INSERT INTO calendar_events 
        (id, title, description, location, color, start_date, end_date, all_day, is_public, repeat_type, created_by, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, body.title, body.description or "", body.location or "", body.color or "#C9A84C",
         body.start_date, body.end_date, 1 if body.all_day else 0, 1 if body.is_public else 0,
         body.repeat_type or "none", user["key"], datetime.datetime.utcnow().isoformat())
    )
    db.commit()
    return {"ok": True, "id": event_id}

@app.put("/api/calendar/{event_id}")
def update_calendar_event(event_id: str, body: CalendarEventRequest, user=Depends(get_current_user), db=Depends(get_db)):
    db.execute("""UPDATE calendar_events SET title=%s, description=%s, location=%s, color=%s, 
        start_date=%s, end_date=%s, all_day=%s, is_public=%s, repeat_type=%s WHERE id=%s""",
        (body.title, body.description or "", body.location or "", body.color or "#C9A84C",
         body.start_date, body.end_date, 1 if body.all_day else 0, 1 if body.is_public else 0,
         body.repeat_type or "none", event_id)
    )
    db.commit()
    return {"ok": True}

@app.delete("/api/calendar/{event_id}")
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
        VALUES (?,?,?,?,?,?)""",
        (point_id, user_key, points, reason, action_type, datetime.datetime.utcnow().isoformat())
    )
    
    # Atualizar pontos totais do usuário
    current_points = target["points"] or 0
    new_total = current_points + points
    db.execute("UPDATE users SET points=%s WHERE key=%s", (new_total, user_key))
    
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
        VALUES (?,?,?,?,?,?,?)""",
        (badge_id, user_key, badge_type, badge_name, description, icon, datetime.datetime.utcnow().isoformat())
    )
    
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
            VALUES (?,?,?,?,?,?,?)""",
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
        VALUES (?,?,?,?,?,?,?)""",
        (achievement_id, user_key, achievement_type, achievement_name, description, icon, datetime.datetime.utcnow().isoformat())
    )
    
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
def delete_calendar_event(event_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    db.execute("DELETE FROM calendar_events WHERE id=%s", (event_id,))
    db.commit()
    return {"ok": True}