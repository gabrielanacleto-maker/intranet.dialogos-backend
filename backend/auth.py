import hashlib, os, jwt, datetime
from typing import Optional

SECRET_KEY = os.getenv("SECRET_KEY", "dialogos_intranet_secret_2025_change_me")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 12

def hash_password(password: str) -> str:
    salt = hashlib.sha256(os.urandom(60)).hexdigest().encode('ascii')
    pwdhash = hashlib.pbkdf2_hmac('sha512', password.encode('utf-8'), salt, 100000)
    pwdhash = pwdhash.hex().encode('ascii')
    return (salt + pwdhash).decode('ascii')

def check_password(provided_password: str, stored_hash: str) -> bool:
    try:
        salt = stored_hash[:64].encode('ascii')
        stored = stored_hash[64:]
        pwdhash = hashlib.pbkdf2_hmac(
            'sha512', provided_password.encode('utf-8'), salt, 100000
        )
        return pwdhash.hex() == stored
    except Exception:
        return False

def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        return None
