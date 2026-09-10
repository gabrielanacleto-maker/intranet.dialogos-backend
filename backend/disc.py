"""Módulo DISC — Avaliação de Perfil Comportamental.

Fluxo (24/25 da especificação):
  1. RH/Admin cria a avaliação para um avaliando -> gera token e retorna o link.
  2. O avaliando abre /disc/avaliacao/{token} numa página independente.
  3. Ao concluir, o frontend envia as respostas para /api/public/disc/{token}/respostas.
  4. O backend REVALIDA tudo (não confia no frontend), recalcula pontuações,
     determina perfis/codenome, salva avaliação e respostas numa única transação
     e marca como concluída.

Permissões:
  - Public: apenas token da avaliação (validado, válido, do avaliando correto,
    com status adequado). Nunca expõe resultados.
  - Authed: CEO / RH / diretoria / admin (validado no backend, não só no front).
"""
import uuid
import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import get_db
from deps import get_current_user, log_action
from disc_data import DISC_CODENAMES, DISC_PERFIS_ROTULO, DISC_PERFIS

router = APIRouter()

DISC_TOTAL_QUESTOES = 25

# ── Modelos Pydantic ──────────────────────────────────────────────────────────

class CriarAvaliacaoRequest(BaseModel):
    avaliando_id: str

class RespostaItem(BaseModel):
    pergunta_id: str
    alternativa_id: str
    pontuacao: int

class EnviarRespostasRequest(BaseModel):
    respostas: list

class SalvarProgressoRequest(BaseModel):
    respostas: list


# ── Helpers de permissão ──────────────────────────────────────────────────────

def _pode_ver_disc(user) -> bool:
    """CEO, diretoria, RH e administradores podem visualizar os resultados."""
    if not user:
        return False
    acesso = bool(
        (user.get("access_level") or 0) >= 2
        or user.get("is_rh")
        or user.get("is_diretor")
        or user.get("is_admin")
        or user.get("is_admin_user")
    )
    return acesso


def _poder_criar(user) -> bool:
    return _pode_ver_disc(user)


# ── Helpers de cálculo ────────────────────────────────────────────────────────

def _calcular_resultado(respostas_validadas: list) -> dict:
    """Recebe respostas já validadas e calcula pontuações e perfis.

    respostas_validadas: lista de {perfil, pontuacao}
    """
    pontos = {p: 0 for p in DISC_PERFIS}
    for r in respostas_validadas:
        pontos[r["perfil"]] += r["pontuacao"]
    total = sum(pontos.values())

    ranking = sorted(pontos.items(), key=lambda kv: (-kv[1], kv[0]))
    perfis_ordenados = [p for p, _ in ranking]

    combinacao = "+".join(sorted(perfis_ordenados)) if perfis_ordenados else ""
    codenome = DISC_CODENAMES.get(combinacao, "")

    resultado = {
        "pontuacao_analista": pontos.get("analista", 0),
        "pontuacao_executor": pontos.get("executor", 0),
        "pontuacao_planejador": pontos.get("planejador", 0),
        "pontuacao_comunicador": pontos.get("comunicador", 0),
        "pontuacao_total": total,
        "perfil_principal": perfis_ordenados[0] if perfis_ordenados else "",
        "segundo_perfil": perfis_ordenados[1] if len(perfis_ordenados) > 1 else "",
        "terceiro_perfil": perfis_ordenados[2] if len(perfis_ordenados) > 2 else "",
        "quarto_perfil": perfis_ordenados[3] if len(perfis_ordenados) > 3 else "",
        "combinacao": combinacao,
        "codenome": codenome,
    }
    return resultado


def _carregar_dados_versao(db, versao_id: str) -> dict:
    """Carrega perguntas e alternativas de uma versão num mapa para validação.

    As alternativas são retornadas na ordem gravada no banco (estável), para
    que o progresso salvo por alternativa_id possa ser restaurado em outra
    carga da página. A variação de ordem entre perguntas já foi feita no seed.
    """
    perguntas = {}
    q_rows = db.execute(
        "SELECT id, texto FROM disc_perguntas WHERE versao_id=%s AND status='ativo' ORDER BY ordem",
        (versao_id,),
    ).fetchall()
    for q in q_rows:
        perguntas[q["id"]] = {
            "id": q["id"],
            "texto": q["texto"],
            "alternativas": {},
        }
    a_rows = db.execute(
        """SELECT id, pergunta_id, texto, perfil FROM disc_alternativas
           WHERE pergunta_id = ANY(%s) ORDER BY ordem""",
        (list(perguntas.keys()),),
    ).fetchall()
    for a in a_rows:
        if a["pergunta_id"] in perguntas:
            perguntas[a["pergunta_id"]]["alternativas"][a["id"]] = {
                "perfil": a["perfil"],
                "texto": a["texto"],
            }
    return perguntas


# ── Endpoints públicos (página independente) ─────────────────────────────────

DISC_HTML = Path(__file__).parent / "static" / "disc.html"

@router.get("/disc/avaliacao/{token}", include_in_schema=False)
def pagina_disc(token: str):
    """Serva a página independente do teste (abre em nova aba)."""
    return FileResponse(DISC_HTML, media_type="text/html")


def _validar_avaliacao_por_token(db, token: str):
    av = db.execute("SELECT * FROM disc_avaliacoes WHERE token=%s", (token,)).fetchone()
    if not av:
        raise HTTPException(status_code=404, detail="Avaliação não encontrada ou link inválido.")
    av = dict(av)
    if av.get("data_expiracao"):
        try:
            exp = datetime.datetime.fromisoformat(av["data_expiracao"])
            if datetime.datetime.utcnow() > exp:
                return av, "expirada"
        except Exception:
            pass
    return av, av.get("status")


@router.get("/api/public/disc/{token}/info")
def disc_info(token: str, db=Depends(get_db)):
    av, status = _validar_avaliacao_por_token(db, token)
    avaliando = db.execute(
        "SELECT name, role, dept, photo_url FROM users WHERE key=%s", (av["avaliando_id"],)
    ).fetchone()
    if not avaliando:
        raise HTTPException(status_code=404, detail="Avaliando não encontrado.")
    versao = db.execute(
        "SELECT nome, total_questoes FROM disc_teste_versoes WHERE id=%s", (av["versao_id"],)
    ).fetchone()
    return {
        "status": status,
        "avaliando": {
            "nome": avaliando["name"],
            "role": avaliando["role"] or "",
            "dept": avaliando["dept"] or "",
            "photo_url": avaliando["photo_url"] or "",
        },
        "versao": versao["nome"] if versao else "DISC",
        "total_questoes": versao["total_questoes"] if versao else DISC_TOTAL_QUESTOES,
        "pode_responder": status in ("pendente", "em_andamento"),
        "ja_concluida": status == "concluida",
    }


@router.get("/api/public/disc/{token}/perguntas")
def disc_perguntas(token: str, db=Depends(get_db)):
    av, status = _validar_avaliacao_por_token(db, token)
    if status == "expirada":
        raise HTTPException(status_code=400, detail="O prazo desta avaliação expirou.")
    if status == "concluida":
        raise HTTPException(status_code=400, detail="Esta avaliação já foi concluída.")
    if status == "pendente":
        db.execute("UPDATE disc_avaliacoes SET status='em_andamento', data_inicio=%s WHERE id=%s",
                   (datetime.datetime.utcnow().isoformat(), av["id"]))
        db.commit()

    perguntas = _carregar_dados_versao(db, av["versao_id"])
    dados = []
    for q in perguntas.values():
        alternativas = [
            {"id": aid, "texto": alt["texto"]}
            for aid, alt in q["alternativas"].items()
        ]
        dados.append({"id": q["id"], "texto": q["texto"], "alternativas": alternativas})
    return {"perguntas": dados}


@router.get("/api/public/disc/{token}/progresso")
def disc_progresso(token: str, db=Depends(get_db)):
    av, status = _validar_avaliacao_por_token(db, token)
    if status == "concluida":
        raise HTTPException(status_code=400, detail="Esta avaliação já foi concluída.")
    respostas = db.execute(
        "SELECT alternativa_id, pergunta_id, perfil_da_alternativa, pontuacao FROM disc_respostas WHERE avaliacao_id=%s",
        (av["id"],),
    ).fetchall()
    return {"respostas": [dict(r) for r in respostas]}


@router.post("/api/public/disc/{token}/progresso")
def disc_salvar_progresso(token: str, body: SalvarProgressoRequest, db=Depends(get_db)):
    av, status = _validar_avaliacao_por_token(db, token)
    if status == "expirada":
        raise HTTPException(status_code=400, detail="O prazo desta avaliação expirou.")
    if status == "concluida":
        raise HTTPException(status_code=400, detail="Esta avaliação já foi concluída.")
    if status == "pendente":
        db.execute("UPDATE disc_avaliacoes SET status='em_andamento', data_inicio=%s WHERE id=%s",
                   (datetime.datetime.utcnow().isoformat(), av["id"]))
    perguntas = _carregar_dados_versao(db, av["versao_id"])
    now = datetime.datetime.utcnow().isoformat()
    for item in body.respostas:
        pid = item.get("pergunta_id")
        aid = item.get("alternativa_id")
        pts = item.get("pontuacao")
        if pid not in perguntas or aid not in perguntas[pid]["alternativas"]:
            continue
        if pts not in (1, 2, 3, 4):
            continue
        db.execute(
            """INSERT INTO disc_respostas (id, avaliacao_id, pergunta_id, alternativa_id, perfil_da_alternativa, pontuacao, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (avaliacao_id, pergunta_id)
               DO UPDATE SET alternativa_id=%s, perfil_da_alternativa=%s, pontuacao=%s""",
            (str(uuid.uuid4()), av["id"], pid, aid, perguntas[pid]["alternativas"][aid]["perfil"], pts, now,
             aid, perguntas[pid]["alternativas"][aid]["perfil"], pts),
        )
    db.commit()
    return {"ok": True}


@router.post("/api/public/disc/{token}/respostas")
def disc_enviar_respostas(token: str, body: EnviarRespostasRequest, db=Depends(get_db)):
    av, status = _validar_avaliacao_por_token(db, token)
    if status == "expirada":
        raise HTTPException(status_code=400, detail="O prazo desta avaliação expirou.")
    if status == "concluida":
        raise HTTPException(status_code=400, detail="Esta avaliação já foi concluída. Não é possível reenviar.")

    # ── Validação completa no backend (não confiar no front) ──
    versao = db.execute("SELECT total_questoes FROM disc_teste_versoes WHERE id=%s", (av["versao_id"],)).fetchone()
    n_necessario = versao["total_questoes"] if versao else DISC_TOTAL_QUESTOES

    perguntas = _carregar_dados_versao(db, av["versao_id"])
    if len(perguntas) != n_necessario:
        raise HTTPException(status_code=400, detail="Configuração do teste inconsistente (número de perguntas).")

    enviadas = body.respostas
    if not enviadas or len(enviadas) < n_necessario:
        raise HTTPException(status_code=400, detail=f"Você deve responder exatamente {n_necessario} perguntas.")

    # Agrupa por pergunta
    por_pergunta = {}
    for item in enviadas:
        pid = item.get("pergunta_id")
        aid = item.get("alternativa_id")
        pts = item.get("pontuacao")
        if pid not in perguntas:
            raise HTTPException(status_code=400, detail="Uma ou mais perguntas não pertencem a este teste.")
        if aid not in perguntas[pid]["alternativas"]:
            raise HTTPException(status_code=400, detail="Alternativa inválida enviada.")
        if pts not in (1, 2, 3, 4):
            raise HTTPException(status_code=400, detail="Valores de pontuação devem ser 1, 2, 3 ou 4.")
        por_pergunta.setdefault(pid, []).append({"alternativa_id": aid, "pontuacao": pts})

    if len(por_pergunta) != n_necessario:
        raise HTTPException(status_code=400, detail="Todas as perguntas devem ser respondidas.")

    respostas_validadas = []
    for pid, respostas in por_pergunta.items():
        if len(respostas) != 4:
            raise HTTPException(status_code=400, detail="Cada pergunta deve ter exatamente quatro respostas.")
        valores = [r["pontuacao"] for r in respostas]
        if sorted(valores) != [1, 2, 3, 4]:
            raise HTTPException(status_code=400, detail="Os valores 1, 2, 3 e 4 devem ser usados exatamente uma vez por pergunta.")
        ids = [r["alternativa_id"] for r in respostas]
        if len(set(ids)) != 4:
            raise HTTPException(status_code=400, detail="Cada alternativa só pode ser usada uma vez por pergunta.")
        for r in respostas:
            respostas_validadas.append({
                "pergunta_id": pid,
                "alternativa_id": r["alternativa_id"],
                "perfil": perguntas[pid]["alternativas"][r["alternativa_id"]]["perfil"],
                "pontuacao": r["pontuacao"],
            })

    # ── Recalcular tudo no backend ──
    resultado = _calcular_resultado(respostas_validadas)

    # ── Salvar em transação única: avaliação + respostas + status ──
    now = datetime.datetime.utcnow().isoformat()
    try:
        db.execute(
            """UPDATE disc_avaliacoes SET
                 status='concluida', data_conclusao=%s,
                 pontuacao_analista=%s, pontuacao_executor=%s, pontuacao_planejador=%s, pontuacao_comunicador=%s,
                 pontuacao_total=%s, perfil_principal=%s, segundo_perfil=%s, terceiro_perfil=%s, quarto_perfil=%s,
                 combinacao=%s, codenome=%s
               WHERE id=%s""",
            (now, resultado["pontuacao_analista"], resultado["pontuacao_executor"],
             resultado["pontuacao_planejador"], resultado["pontuacao_comunicador"],
             resultado["pontuacao_total"], resultado["perfil_principal"], resultado["segundo_perfil"],
             resultado["terceiro_perfil"], resultado["quarto_perfil"],
             resultado["combinacao"], resultado["codenome"], av["id"]),
        )
        db.execute("DELETE FROM disc_respostas WHERE avaliacao_id=%s", (av["id"],))
        for r in respostas_validadas:
            db.execute(
                """INSERT INTO disc_respostas (id, avaliacao_id, pergunta_id, alternativa_id, perfil_da_alternativa, pontuacao, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid.uuid4()), av["id"], r["pergunta_id"], r["alternativa_id"],
                 r["perfil"], r["pontuacao"], now),
            )
        # Propaga perfil predominante para o campo users.disc (se ainda vazio)
        db.execute(
            "UPDATE users SET disc=%s WHERE key=%s AND (disc IS NULL OR disc='')",
            (resultado["perfil_principal"], av["avaliando_id"]),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Não foi possível registrar a avaliação. Tente novamente.")

    return {
        "ok": True,
        "mensagem": "Avaliação concluída com sucesso.",
        "status": "concluida",
    }


# ── Endpoints autenticados (criação + painéis) ───────────────────────────────

@router.post("/api/disc/avaliacoes")
def criar_avaliacao(body: CriarAvaliacaoRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if not _poder_criar(user):
        raise HTTPException(status_code=403, detail="Sem permissão para criar avaliações DISC.")
    avaliando = db.execute("SELECT key, name FROM users WHERE key=%s", (body.avaliando_id,)).fetchone()
    if not avaliando:
        raise HTTPException(status_code=404, detail="Avaliando não encontrado.")

    # Impede duplicação de avaliação ativa para o mesmo avaliando
    dup = db.execute(
        """SELECT id FROM disc_avaliacoes
           WHERE avaliando_id=%s AND status IN ('pendente','em_andamento')""",
        (body.avaliando_id,),
    ).fetchone()
    if dup:
        raise HTTPException(status_code=409, detail="Este colaborador já possui uma avaliação pendente ou em andamento.")

    versao = db.execute(
        "SELECT id FROM disc_teste_versoes WHERE ativo=1 ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if not versao:
        raise HTTPException(status_code=500, detail="Nenhuma versão do teste ativa.")

    av_id = str(uuid.uuid4())
    token = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    db.execute(
        """INSERT INTO disc_avaliacoes (id, avaliando_id, solicitante_id, token, versao_id, status, data_inicio, created_at)
           VALUES (%s,%s,%s,%s,%s,'pendente',NULL,%s)""",
        (av_id, body.avaliando_id, user["key"], token, versao["id"], now),
    )
    db.commit()
    log_action(db, user["key"], body.avaliando_id, "DISC - Criar Avaliação",
               f"Criou avaliação DISC para {avaliando['name']}")
    link = f"/disc/avaliacao/{token}"
    return {
        "id": av_id,
        "avaliando_id": body.avaliando_id,
        "status": "pendente",
        "link": link,
        "link_absoluto": link,
    }


def _anexa_dados_colaborador(db, itens):
    """Enriquece cada avaliação com dados do colaborador (nome, cargo, dept, empresa)."""
    resultado = []
    for av in itens:
        u = db.execute(
            "SELECT name, role, dept, cargo_id, departamento_id, empresa_id, hire_date FROM users WHERE key=%s",
            (av["avaliando_id"],),
        ).fetchone()
        cargo_nome = ""
        dept_nome = ""
        if u and u["cargo_id"]:
            c = db.execute("SELECT nome FROM cargos WHERE id=%s", (u["cargo_id"],)).fetchone()
            if c:
                cargo_nome = c["nome"]
        if u and u["departamento_id"]:
            d = db.execute("SELECT nome FROM departamentos WHERE id=%s", (u["departamento_id"],)).fetchone()
            if d:
                dept_nome = d["nome"]
        data = dict(av)
        data["colaborador_nome"] = u["name"] if u else ""
        data["colaborador_cargo"] = (u["role"] if u else "") or cargo_nome
        data["colaborador_dept"] = (u["dept"] if u else "") or dept_nome
        data["empresa_id"] = u["empresa_id"] if u else None
        data["hire_date"] = u["hire_date"] if u else ""
        resultado.append(data)
    return resultado


@router.get("/api/disc/avaliacoes")
def listar_avaliacoes(
    user=Depends(get_current_user),
    db=Depends(get_db),
    status: Optional[str] = None,
    perfil: Optional[str] = None,
    departamento_id: Optional[str] = None,
    cargo_id: Optional[str] = None,
    search: Optional[str] = None,
    ordenar_por: Optional[str] = None,
):
    if not _pode_ver_disc(user):
        raise HTTPException(status_code=403, detail="Sem permissão para visualizar resultados DISC.")

    sql = "SELECT * FROM disc_avaliacoes WHERE 1=1"
    params = []
    if status:
        sql += " AND status=%s"
        params.append(status)
    if perfil:
        sql += " AND perfil_principal=%s"
        params.append(perfil)
    if departamento_id:
        sql += " AND avaliando_id IN (SELECT key FROM users WHERE departamento_id=%s)"
        params.append(departamento_id)
    if cargo_id:
        sql += " AND avaliando_id IN (SELECT key FROM users WHERE cargo_id=%s)"
        params.append(cargo_id)
    if search:
        sql += " AND avaliando_id IN (SELECT key FROM users WHERE LOWER(name) LIKE %s OR LOWER(email) LIKE %s OR LOWER(role) LIKE %s)"
        like = f"%{search.lower()}%"
        params += [like, like, like]

    if ordenar_por == "pontuacao":
        sql += " ORDER BY pontuacao_total DESC"
    else:
        sql += " ORDER BY data_conclusao DESC NULLS LAST, data_inicio DESC NULLS LAST"

    rows = [dict(r) for r in db.execute(sql, tuple(params) if params else None).fetchall()]
    itens = _anexa_dados_colaborador(db, rows)
    return {"avaliacoes": itens}


@router.get("/api/disc/avaliacoes/{avaliacao_id}")
def detalhe_avaliacao(avaliacao_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    if not _pode_ver_disc(user):
        raise HTTPException(status_code=403, detail="Sem permissão para visualizar resultados DISC.")
    av = db.execute("SELECT * FROM disc_avaliacoes WHERE id=%s", (avaliacao_id,)).fetchone()
    if not av:
        raise HTTPException(status_code=404, detail="Avaliação não encontrada.")
    av = dict(av)

    u = db.execute(
        "SELECT name, role, dept, cargo_id, departamento_id, empresa_id, hire_date FROM users WHERE key=%s",
        (av["avaliando_id"],),
    ).fetchone()
    cargo_nome = ""
    dept_nome = ""
    if u and u["cargo_id"]:
        c = db.execute("SELECT nome FROM cargos WHERE id=%s", (u["cargo_id"],)).fetchone()
        if c:
            cargo_nome = c["nome"]
    if u and u["departamento_id"]:
        d = db.execute("SELECT nome FROM departamentos WHERE id=%s", (u["departamento_id"],)).fetchone()
        if d:
            dept_nome = d["nome"]

    respostas = db.execute(
        "SELECT pergunta_id, perfil_da_alternativa, pontuacao FROM disc_respostas WHERE avaliacao_id=%s ORDER BY created_at",
        (avaliacao_id,),
    ).fetchall()

    return {
        "avaliacao": av,
        "colaborador_nome": u["name"] if u else "",
        "colaborador_cargo": (u["role"] if u else "") or cargo_nome,
        "colaborador_dept": (u["dept"] if u else "") or dept_nome,
        "empresa_id": u["empresa_id"] if u else None,
        "hire_date": u["hire_date"] if u else "",
        "respostas": [dict(r) for r in respostas],
        "perfis_rotulo": DISC_PERFIS_ROTULO,
    }


@router.get("/api/disc/filtros")
def filtros_disc(user=Depends(get_current_user), db=Depends(get_db)):
    if not _pode_ver_disc(user):
        raise HTTPException(status_code=403, detail="Sem permissão.")
    departamentos = [dict(r) for r in db.execute(
        "SELECT id, nome FROM departamentos ORDER BY nome").fetchall()]
    cargos = [dict(r) for r in db.execute(
        "SELECT id, nome FROM cargos WHERE COALESCE(ativo,1)=1 ORDER BY nome").fetchall()]
    return {
        "perfis": [{"valor": p, "rotulo": DISC_PERFIS_ROTULO.get(p, p)} for p in DISC_PERFIS],
        "departamentos": departamentos,
        "cargos": cargos,
    }
