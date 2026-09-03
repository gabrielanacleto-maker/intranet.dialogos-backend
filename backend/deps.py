"""Dependências compartilhadas (auth, cache de usuário, auditoria).

Extraído de main.py para permitir que routers auxiliares (ex.: rh_estrutura)
reutilizem a mesma lógica sem gerar import circular.
"""
import time
import uuid
import datetime

from fastapi import HTTPException, Depends, Query, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_db_context
from auth import verify_token

security = HTTPBearer(auto_error=False)

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


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            raise HTTPException(status_code=401, detail="Token ausente")
        payload = verify_token(credentials.credentials)
        if not payload:
            raise HTTPException(status_code=401, detail="Token inválido ou expirado")

        cached = _get_user_cache(payload["sub"])
        if cached:
            if cached.get("desligado"):
                raise HTTPException(status_code=403, detail="Usuário desligado.")
            return cached

        with get_db_context() as db:
            user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
            if not user_row:
                raise HTTPException(status_code=401, detail="Usuário não encontrado")
            user_data = dict(user_row)
            if user_data.get("desligado"):
                raise HTTPException(status_code=403, detail="Usuário desligado.")
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
        if cached.get("desligado"):
            raise HTTPException(status_code=403, detail="Usuário desligado.")
        return cached

    with get_db_context() as db:
        user_row = db.execute("SELECT * FROM users WHERE key=%s", (payload["sub"],)).fetchone()
        if not user_row:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")
        user_data = dict(user_row)
        if user_data.get("desligado"):
            raise HTTPException(status_code=403, detail="Usuário desligado.")
        _set_user_cache(payload["sub"], user_data)
        return user_data


def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials:
            return None
        try:
            return get_current_user(credentials)
        except Exception:
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
