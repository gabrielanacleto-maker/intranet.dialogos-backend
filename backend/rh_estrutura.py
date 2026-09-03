"""
Módulo de Cargos & Carreira genérico e multiempresa (SaaS).

Conceitos separados e escopados por tenant (empresa):
  - Departamentos (áreas)
  - Famílias de Cargo (agrupamento opcional)
  - Trilhas/Categorias (opcional)
  - Senioridades (ativável por empresa)
  - Níveis Hierárquicos (ativável por empresa)
  - Cargos (carregam área/família/trilha/nível hierárquico)

Regras centrais:
  - Isolamento por empresa: nível >= 3 administra qualquer empresa;
    nível 2 somente a própria (empresa_id do seu cadastro).
  - Exclusão física só quando não houver vínculos; caso contrário HTTP 409
    sugerindo desativação (preserva histórico).
  - Sem escada universal: nenhuma progressão é inferida pelo sistema.
"""
import re
import uuid
import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from models import EstruturaItemRequest, CargoEstruturaRequest
from database import get_db
from deps import get_current_user, require_level, log_action

router = APIRouter()

# ── Configuração das entidades ───────────────────────────────────────────────

CATALOGOS = {
    "departamentos": {"tabela": "departamentos", "rotulo": "Departamento"},
    "familias": {"tabela": "familias_cargo", "rotulo": "Família de Cargo"},
    "trilhas": {"tabela": "trilhas", "rotulo": "Trilha"},
    "senioridades": {"tabela": "senioridades", "rotulo": "Senioridade"},
    "niveis-hierarquicos": {"tabela": "niveis_hierarquicos", "rotulo": "Nível Hierárquico"},
}

# Referências que bloqueiam exclusão física: entidade -> [(tabela, coluna)]
REFERENCIAS = {
    "departamentos": [("cargos", "departamento_id")],
    "familias": [("cargos", "familia_id")],
    "trilhas": [("cargos", "trilha_id")],
    "senioridades": [("users", "senioridade_id"), ("carreira_historico", "senioridade_id")],
    "niveis-hierarquicos": [("cargos", "nivel_hierarquico_id")],
}


def _cfg(entidade: str) -> dict:
    cfg = CATALOGOS.get(entidade)
    if not cfg:
        raise HTTPException(status_code=404, detail="Entidade desconhecida.")
    return cfg


# ── Helpers de tenant ────────────────────────────────────────────────────────

def _empresas_permitidas(user, db) -> set:
    """Empresas visíveis/gerenciáveis pelo usuário autenticado."""
    if (user.get("access_level") or 0) >= 3:
        return {r["id"] for r in db.execute("SELECT id FROM empresas").fetchall()}
    return {user.get("empresa_id") or "dialogos"}


def _resolver_empresa(user, db, requested: Optional[str]) -> str:
    """Valida e retorna a empresa alvo da operação."""
    permitidas = _empresas_permitidas(user, db)
    alvo = (requested or "").strip() or (user.get("empresa_id") or "dialogos")
    if alvo not in permitidas:
        raise HTTPException(status_code=403,
                            detail="Você não tem permissão para acessar a estrutura desta empresa.")
    existe = db.execute("SELECT 1 FROM empresas WHERE id=%s", (alvo,)).fetchone()
    if not existe:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    return alvo


def _contar_vinculos(db, tabela_ref: str, coluna_ref: str, item_id: str) -> int:
    row = db.execute(
        f"SELECT COUNT(*) AS n FROM {tabela_ref} WHERE {coluna_ref}=%s", (item_id,)
    ).fetchone()
    return row["n"] or 0


def _validar_fk_empresa(db, empresa_id: str, tabela: str, coluna: str, valor: Optional[str], rotulo: str):
    """Garante que um registro opcional pertence à mesma empresa."""
    if not valor:
        return None
    row = db.execute(
        f"SELECT id FROM {tabela} WHERE id=%s AND empresa_id=%s", (valor, empresa_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400,
                            detail=f"{rotulo} informado não pertence à empresa selecionada.")
    return valor


def _slug(nome: str, prefixo: str) -> str:
    base = re.sub(r'[^a-z0-9]+', '-', nome.lower()).strip('-') or prefixo
    return base


def _gerar_id_unico(db, tabela: str, base: str) -> str:
    candidato, n = base, 1
    while db.execute(f"SELECT 1 FROM {tabela} WHERE id=%s", (candidato,)).fetchone():
        candidato = f"{base}-{n}"
        n += 1
    return candidato


# ── Catálogos genéricos (CRUD multiempresa) ──────────────────────────────────

@router.get("/api/rh/{entidade}")
def listar_entidade(entidade: str, empresa_id: Optional[str] = None, q: Optional[str] = None,
                    include_inactive: bool = False,
                    user=Depends(get_current_user), db=Depends(get_db)):
    cfg = _cfg(entidade)
    empresa = _resolver_empresa(user, db, empresa_id)
    where = ["empresa_id=%s"]
    params = [empresa]
    if not include_inactive:
        where.append("ativo=1")
    if q:
        where.append("LOWER(nome) LIKE LOWER(%s)")
        params.append(f"%{q.strip()}%")
    rows = db.execute(
        f"SELECT * FROM {cfg['tabela']} WHERE {' AND '.join(where)} ORDER BY ordem ASC, nome ASC",
        params,
    ).fetchall()

    resultado = []
    for r in rows:
        item = dict(r)
        item["ativo"] = bool(item.get("ativo"))
        vinculos = 0
        for tabela_ref, coluna_ref in REFERENCIAS.get(entidade, []):
            vinculos += _contar_vinculos(db, tabela_ref, coluna_ref, r["id"])
        item["vinculos"] = vinculos
        resultado.append(item)
    return {"empresa_id": empresa, "itens": resultado}


@router.post("/api/rh/{entidade}")
def criar_entidade(entidade: str, body: EstruturaItemRequest, empresa_id: Optional[str] = None,
                   user=Depends(require_level(2)), db=Depends(get_db)):
    cfg = _cfg(entidade)
    nome = (body.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail=f"Nome do {cfg['rotulo'].lower()} é obrigatório.")
    empresa = _resolver_empresa(user, db, empresa_id)

    dup = db.execute(
        f"SELECT 1 FROM {cfg['tabela']} WHERE empresa_id=%s AND LOWER(nome)=LOWER(%s)",
        (empresa, nome),
    ).fetchone()
    if dup:
        raise HTTPException(status_code=409,
                            detail=f"Já existe um {cfg['rotulo'].lower()} com este nome nesta empresa.")

    novo_id = str(uuid.uuid4())
    db.execute(
        f"""INSERT INTO {cfg['tabela']} (id, empresa_id, nome, descricao, ordem, ativo, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (novo_id, empresa, nome, (body.descricao or "").strip(), int(body.ordem or 0),
         1 if body.ativo else 0, datetime.datetime.utcnow().isoformat()),
    )
    log_action(db, user["key"], novo_id, f"Criação de {cfg['rotulo']}",
               f"Criou '{nome}' na empresa {empresa}")
    db.commit()
    return {"id": novo_id, "ok": True}


@router.put("/api/rh/{entidade}/{item_id}")
def editar_entidade(entidade: str, item_id: str, body: EstruturaItemRequest,
                    user=Depends(require_level(2)), db=Depends(get_db)):
    cfg = _cfg(entidade)
    row = db.execute(f"SELECT * FROM {cfg['tabela']} WHERE id=%s", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{cfg['rotulo']} não encontrado.")
    _resolver_empresa(user, db, row["empresa_id"])

    nome = (body.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail=f"Nome do {cfg['rotulo'].lower()} é obrigatório.")
    dup = db.execute(
        f"""SELECT 1 FROM {cfg['tabela']}
            WHERE empresa_id=%s AND LOWER(nome)=LOWER(%s) AND id<>%s""",
        (row["empresa_id"], nome, item_id),
    ).fetchone()
    if dup:
        raise HTTPException(status_code=409,
                            detail=f"Já existe um {cfg['rotulo'].lower()} com este nome nesta empresa.")

    db.execute(
        f"""UPDATE {cfg['tabela']}
            SET nome=%s, descricao=%s, ordem=%s, ativo=%s
            WHERE id=%s""",
        (nome, (body.descricao or "").strip(), int(body.ordem or 0),
         1 if body.ativo else 0, item_id),
    )
    acao = f"Atualização de {cfg['rotulo']}"
    detalhe = f"Atualizou '{nome}'"
    if bool(row["ativo"]) != body.ativo:
        detalhe += " (reativado)" if body.ativo else " (desativado)"
    log_action(db, user["key"], item_id, acao, detalhe)
    db.commit()
    return {"ok": True}


@router.delete("/api/rh/{entidade}/{item_id}")
def excluir_entidade(entidade: str, item_id: str,
                     user=Depends(require_level(2)), db=Depends(get_db)):
    cfg = _cfg(entidade)
    row = db.execute(f"SELECT * FROM {cfg['tabela']} WHERE id=%s", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"{cfg['rotulo']} não encontrado.")
    _resolver_empresa(user, db, row["empresa_id"])

    total = 0
    for tabela_ref, coluna_ref in REFERENCIAS.get(entidade, []):
        total += _contar_vinculos(db, tabela_ref, coluna_ref, item_id)
    if total > 0:
        raise HTTPException(
            status_code=409,
            detail=(f"Este {cfg['rotulo'].lower()} está em uso por {total} registro(s). "
                    "Desative-o para preservar o histórico."),
        )

    db.execute(f"DELETE FROM {cfg['tabela']} WHERE id=%s", (item_id,))
    log_action(db, user["key"], item_id, f"Exclusão de {cfg['rotulo']}",
               f"Excluiu '{row['nome']}'")
    db.commit()
    return {"ok": True}


# ── Cargos ───────────────────────────────────────────────────────────────────

_CARGO_SELECT = """
    SELECT c.id, c.nome, c.nivel, c.empresa_id, c.departamento_id, c.familia_id,
           c.trilha_id, c.nivel_hierarquico_id, c.descricao, c.ativo, c.created_at,
           d.nome AS departamento_nome,
           f.nome AS familia_nome,
           t.nome AS trilha_nome,
           n.nome AS nivel_hierarquico_nome,
           (SELECT COUNT(*) FROM users u WHERE u.cargo_id = c.id AND u.desligado = 0) AS usuarios
    FROM cargos c
    LEFT JOIN departamentos d ON d.id = c.departamento_id
    LEFT JOIN familias_cargo f ON f.id = c.familia_id
    LEFT JOIN trilhas t ON t.id = c.trilha_id
    LEFT JOIN niveis_hierarquicos n ON n.id = c.nivel_hierarquico_id
"""

def _serializar_cargo(r) -> dict:
    d = dict(r)
    d["ativo"] = bool(d.get("ativo"))
    d["usuarios"] = d.get("usuarios") or 0
    return d


def _validar_estrutura_cargo(db, empresa_id: str, body: CargoEstruturaRequest) -> dict:
    return {
        "departamento_id": _validar_fk_empresa(db, empresa_id, "departamentos", "departamento_id",
                                               body.departamento_id, "Departamento"),
        "familia_id": _validar_fk_empresa(db, empresa_id, "familias_cargo", "familia_id",
                                          body.familia_id, "Família de Cargo"),
        "trilha_id": _validar_fk_empresa(db, empresa_id, "trilhas", "trilha_id",
                                         body.trilha_id, "Trilha"),
        "nivel_hierarquico_id": _validar_fk_empresa(db, empresa_id, "niveis_hierarquicos",
                                                    "nivel_hierarquico_id", body.nivel_hierarquico_id,
                                                    "Nível hierárquico"),
    }


@router.get("/api/cargos")
def list_cargos(empresa_id: Optional[str] = None, departamento_id: Optional[str] = None,
                q: Optional[str] = None, include_inactive: bool = False,
                user=Depends(get_current_user), db=Depends(get_db)):
    empresa = _resolver_empresa(user, db, empresa_id)
    where = ["c.empresa_id=%s"]
    params = [empresa]
    if departamento_id:
        where.append("c.departamento_id=%s")
        params.append(departamento_id)
    if not include_inactive:
        where.append("c.ativo=1")
    if q:
        where.append("LOWER(c.nome) LIKE LOWER(%s)")
        params.append(f"%{q.strip()}%")
    rows = db.execute(
        _CARGO_SELECT + f"WHERE {' AND '.join(where)} ORDER BY c.nivel ASC, c.nome ASC",
        params,
    ).fetchall()
    return [_serializar_cargo(r) for r in rows]


@router.post("/api/cargos")
def create_cargo(body: CargoEstruturaRequest, user=Depends(require_level(2)), db=Depends(get_db)):
    empresa_alvo = body.empresa_id if (user.get("access_level") or 0) >= 3 and body.empresa_id else None
    empresa = _resolver_empresa(user, db, empresa_alvo)
    nome = (body.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do cargo é obrigatório.")

    dup = db.execute(
        "SELECT 1 FROM cargos WHERE empresa_id=%s AND LOWER(nome)=LOWER(%s)",
        (empresa, nome),
    ).fetchone()
    if dup:
        raise HTTPException(status_code=409, detail="Já existe um cargo com este nome nesta empresa.")

    estrutura = _validar_estrutura_cargo(db, empresa, body)
    cargo_id = _gerar_id_unico(db, "cargos", _slug(nome, "cargo"))

    db.execute(
        """INSERT INTO cargos
               (id, nome, nivel, created_at, empresa_id, departamento_id, familia_id,
                trilha_id, nivel_hierarquico_id, descricao, ativo)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (cargo_id, nome, int(body.nivel or 0), datetime.datetime.utcnow().isoformat(),
         empresa, estrutura["departamento_id"], estrutura["familia_id"],
         estrutura["trilha_id"], estrutura["nivel_hierarquico_id"],
         (body.descricao or "").strip(), 1 if body.ativo else 0),
    )
    log_action(db, user["key"], cargo_id, "Criação de Cargo",
               f"Criou o cargo {nome} na empresa {empresa}")
    db.commit()
    return {"id": cargo_id, "ok": True}


@router.put("/api/cargos/{cargo_id}")
def update_cargo(cargo_id: str, body: CargoEstruturaRequest,
                 user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM cargos WHERE id=%s", (cargo_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cargo não encontrado.")
    _resolver_empresa(user, db, row["empresa_id"])

    nome = (body.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome do cargo é obrigatório.")
    dup = db.execute(
        "SELECT 1 FROM cargos WHERE empresa_id=%s AND LOWER(nome)=LOWER(%s) AND id<>%s",
        (row["empresa_id"], nome, cargo_id),
    ).fetchone()
    if dup:
        raise HTTPException(status_code=409, detail="Já existe um cargo com este nome nesta empresa.")

    estrutura = _validar_estrutura_cargo(db, row["empresa_id"], body)
    db.execute(
        """UPDATE cargos SET nome=%s, nivel=%s, departamento_id=%s, familia_id=%s,
               trilha_id=%s, nivel_hierarquico_id=%s, descricao=%s, ativo=%s
           WHERE id=%s""",
        (nome, int(body.nivel or 0), estrutura["departamento_id"], estrutura["familia_id"],
         estrutura["trilha_id"], estrutura["nivel_hierarquico_id"],
         (body.descricao or "").strip(), 1 if body.ativo else 0, cargo_id),
    )
    detalhe = f"Atualizou o cargo para {nome}"
    if bool(row["ativo"]) != body.ativo:
        detalhe += " (reativado)" if body.ativo else " (desativado)"
    log_action(db, user["key"], cargo_id, "Atualização de Cargo", detalhe)
    db.commit()
    return {"ok": True}


@router.delete("/api/cargos/{cargo_id}")
def delete_cargo(cargo_id: str, user=Depends(require_level(2)), db=Depends(get_db)):
    row = db.execute("SELECT * FROM cargos WHERE id=%s", (cargo_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cargo não encontrado.")
    _resolver_empresa(user, db, row["empresa_id"])

    vinculados = _contar_vinculos(db, "users", "cargo_id", cargo_id)
    if vinculados > 0:
        raise HTTPException(
            status_code=409,
            detail=(f"Este cargo está atribuído a {vinculados} colaborador(es). "
                    "Desative-o para preservar o histórico."),
        )
    db.execute("DELETE FROM cargos WHERE id=%s", (cargo_id,))
    log_action(db, user["key"], cargo_id, "Exclusão de Cargo", f"Excluiu o cargo {row['nome']}")
    db.commit()
    return {"ok": True}


# ── Catálogo completo para o formulário de colaborador ──────────────────────

@router.get("/api/catalogo-vinculo")
def catalogo_vinculo(empresa_id: Optional[str] = None, include_inactive: bool = False,
                     user=Depends(get_current_user), db=Depends(get_db)):
    empresa = _resolver_empresa(user, db, empresa_id)
    filtro = "" if include_inactive else "AND ativo=1"

    def lista(tabela):
        rows = db.execute(
            f"SELECT * FROM {tabela} WHERE empresa_id=%s {filtro} ORDER BY ordem ASC, nome ASC",
            (empresa,),
        ).fetchall()
        resultado = []
        for r in rows:
            item = dict(r)
            item["ativo"] = bool(item.get("ativo"))
            resultado.append(item)
        return resultado

    where_cargos = "WHERE c.empresa_id=%s"
    if not include_inactive:
        where_cargos += " AND c.ativo=1"
    cargos_rows = db.execute(
        _CARGO_SELECT + where_cargos + " ORDER BY c.nivel ASC, c.nome ASC",
        (empresa,),
    ).fetchall()

    return {
        "empresa_id": empresa,
        "departamentos": lista("departamentos"),
        "familias": lista("familias_cargo"),
        "trilhas": lista("trilhas"),
        "senioridades": lista("senioridades"),
        "niveis_hierarquicos": lista("niveis_hierarquicos"),
        "cargos": [_serializar_cargo(r) for r in cargos_rows],
    }


# ── Vínculo estrutural de um colaborador ────────────────────────────────────

@router.get("/api/rh/vinculo/{user_key}")
def vinculo_usuario(user_key: str, user=Depends(get_current_user), db=Depends(get_db)):
    target = db.execute("SELECT key FROM users WHERE key=%s", (user_key,)).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    row = db.execute(
        """
        SELECT u.key, u.name, u.role, u.dept, u.cargo_id, u.senioridade, u.senioridade_id,
               u.departamento_id, u.empresa_id,
                c.nome AS cargo_nome, c.descricao AS cargo_descricao,
                c.familia_id, c.trilha_id, c.nivel_hierarquico_id,
               d.nome AS departamento_nome,
               f.nome AS familia_nome,
               t.nome AS trilha_nome,
               s.nome AS senioridade_nome,
               n.nome AS nivel_hierarquico_nome,
               e.nome AS empresa_nome, e.logo AS empresa_logo
        FROM users u
        LEFT JOIN cargos c ON c.id = u.cargo_id
        LEFT JOIN departamentos d ON d.id = COALESCE(u.departamento_id, c.departamento_id)
        LEFT JOIN familias_cargo f ON f.id = c.familia_id
        LEFT JOIN trilhas t ON t.id = c.trilha_id
        LEFT JOIN senioridades s ON s.id = u.senioridade_id
        LEFT JOIN niveis_hierarquicos n ON n.id = c.nivel_hierarquico_id
        LEFT JOIN empresas e ON e.id = u.empresa_id
        WHERE u.key = %s
        """,
        (user_key,),
    ).fetchone()
    data = dict(row)
    # Fallbacks legados
    if not data.get("departamento_nome"):
        data["departamento_nome"] = data.get("dept") or ""
    if not data.get("senioridade_nome"):
        legado = {"jr": "Júnior", "pl": "Pleno", "sr": "Sênior"}.get(
            (data.get("senioridade") or "").lower(), "")
        data["senioridade_nome"] = legado or ""
    return data
