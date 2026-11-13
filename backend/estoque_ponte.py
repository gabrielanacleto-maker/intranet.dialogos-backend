"""Ponte de login: intranet -> Estoque em Foco (Supabase Auth).

O intranet tem o próprio cadastro de usuários. O estoque usa Supabase Auth, e a
chave de serviço do Supabase fica só no lado do estoque (Lovable Cloud).

Quando o colaborador logado clica em "Estoque", este endpoint pede ao estoque
(/api/intranet-login, protegido por INTRANET_BRIDGE_SECRET) um token de login de uso
único para o e-mail dele. O frontend abre o link no estoque, que troca o token por
uma sessão.
"""
import logging
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException

from deps import get_current_user

log = logging.getLogger("estoque_ponte")

router = APIRouter()

ESTOQUE_URL = os.getenv("ESTOQUE_URL", "").strip().rstrip("/")
INTRANET_BRIDGE_SECRET = os.getenv("INTRANET_BRIDGE_SECRET", "").strip()

_FALHA = "Não foi possível abrir o estoque agora. Tente de novo."


@router.post("/api/estoque/link")
def estoque_link(user=Depends(get_current_user)):
    if not (ESTOQUE_URL and INTRANET_BRIDGE_SECRET):
        log.error("Ponte do estoque sem configuração (ESTOQUE_URL ou INTRANET_BRIDGE_SECRET)")
        raise HTTPException(status_code=503, detail="Acesso ao estoque não está configurado. Avise a TI.")

    email = (user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Seu cadastro não tem e-mail. Peça ao RH para cadastrá-lo.")

    try:
        res = httpx.post(
            f"{ESTOQUE_URL}/api/intranet-login",
            headers={"Authorization": f"Bearer {INTRANET_BRIDGE_SECRET}"},
            json={"email": email},
            timeout=15,
        )
    except httpx.HTTPError:
        log.exception("Falha de rede ao falar com o estoque")
        raise HTTPException(status_code=502, detail=_FALHA)

    if res.status_code == 401:
        log.error("Estoque recusou o INTRANET_BRIDGE_SECRET: segredo diferente nos dois lados")
        raise HTTPException(status_code=503, detail="Acesso ao estoque não está configurado. Avise a TI.")
    if res.status_code == 404:
        raise HTTPException(status_code=404, detail="Seu e-mail não tem acesso ao estoque. Peça cadastro à administração.")
    if res.status_code == 503:
        log.error("Estoque sem INTRANET_BRIDGE_SECRET configurado")
        raise HTTPException(status_code=503, detail="Acesso ao estoque não está configurado. Avise a TI.")
    if res.status_code != 200:
        log.error("Estoque respondeu %s em /api/intranet-login: %s", res.status_code, res.text[:200])
        raise HTTPException(status_code=502, detail=_FALHA)

    token_hash = (res.json() or {}).get("token_hash")
    if not token_hash:
        log.error("Estoque não devolveu token_hash")
        raise HTTPException(status_code=502, detail=_FALHA)

    return {"url": f"{ESTOQUE_URL}/auth?token_hash={quote(token_hash)}&type=magiclink"}
