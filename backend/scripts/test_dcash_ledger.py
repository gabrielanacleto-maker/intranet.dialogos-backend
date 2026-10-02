"""Teste da Parte 3: ledger de D-Cash fecha a auditoria.

Cobre:
  - credito e debito pelo funil unico
  - debito maior que o saldo (trunca e ainda reconcilia)
  - saldo nao fica negativo
  -ancoragem idempotente
  - regressao: salvar o perfil NAO pode mexer no saldo
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
from database import init_db
from auth import hash_password, create_token

load_dotenv()
init_db()

TESTE = "ZZ_TESTE_LEDGER"
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def limpar():
    for t, c in (("user_points","user_key"), ("daily_rewards","user_key"),
                 ("notifications","target_user_key"), ("mood_daily_lock","user_key"),
                 ("mood_history","user_key"), ("presence","user_key"), ("users","key")):
        cur.execute(f"DELETE FROM {t} WHERE {c}=%s", (TESTE,))
limpar()

cur.execute("""INSERT INTO users (key,name,initials,role,dept,level,color,
               access_level,points,password_hash,hire_date,org_position)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (TESTE,"Teste Ledger","TL","Teste","TI","JR","av-gold",3,0,
             hash_password("Teste@12345"),"2026-01-01","colaborador"))

from fastapi.testclient import TestClient
from main import app, _movimentar_dcash
from database import get_db_context
client = TestClient(app)
H = {"Authorization": f"Bearer {create_token({'sub': TESTE, 'role': 'user'})}"}

def saldo():
    cur.execute("SELECT COALESCE(points,0) p FROM users WHERE key=%s", (TESTE,))
    return cur.fetchone()["p"]

def ledger():
    cur.execute("SELECT COALESCE(SUM(points),0) s, COUNT(*) n FROM user_points WHERE user_key=%s", (TESTE,))
    r = cur.fetchone(); return r["s"], r["n"]

def confere(rotulo):
    s, n = ledger()
    ok = s == saldo()
    print(f"   {rotulo:<46} saldo={saldo():>4}  ledger={s:>4} ({n} lanc)  {'OK' if ok else '<<< DIVERGE'}")
    return ok

TODAS = []
print("=" * 74); print("1) Creditos e debitos pelo funil unico"); print("=" * 74)
with get_db_context() as db:
    _movimentar_dcash(db, TESTE, 100, "Credito inicial", "teste")
    db.commit()
TODAS.append(confere("credito +100"))
with get_db_context() as db:
    _movimentar_dcash(db, TESTE, -30, "Gasto em recompensa", "gasto")
    db.commit()
TODAS.append(confere("debito -30"))
with get_db_context() as db:
    _movimentar_dcash(db, TESTE, 10, "Bonus", "teste")
    db.commit()
TODAS.append(confere("credito +10"))
print(f"   saldo esperado: 80  -> {'OK' if saldo() == 80 else '<<< FALHOU, saldo=' + str(saldo())}")
TODAS.append(saldo() == 80)

print(); print("=" * 74); print("2) Debito maior que o saldo (trunca, nao fica negativo)"); print("=" * 74)
with get_db_context() as db:
    mov = _movimentar_dcash(db, TESTE, -500, "Gasto maior que o saldo", "gasto")
    db.commit()
print(f"   _movimentar_dcash retornou {mov}   (delta_efetivo, saldo_apos)")
print(f"   saldo={saldo()}  -> {'OK: trancou em 0' if saldo() == 0 else '<<< FALHOU'}")
TODAS.append(saldo() == 0)
TODAS.append(confere("ledger ainda bate depois do tranco"))

print(); print("=" * 74); print("3) Debito em saldo zerado (nao grava lancamento fantasma)"); print("=" * 74)
antes = ledger()[1]
with get_db_context() as db:
    mov = _movimentar_dcash(db, TESTE, -25, "Debito sem saldo", "gasto")
    db.commit()
print(f"   retornou {mov}, lancamentos {antes} -> {ledger()[1]}")
TODAS.append(ledger()[1] == antes)
TODAS.append(confere("ledger intacto"))

print(); print("=" * 74); print("4) Saldo_apos forms a cadeia"); print("=" * 74)
cur.execute("""SELECT points, saldo_apos, action_type, reason FROM user_points
               WHERE user_key=%s ORDER BY created_at, id""", (TESTE,))
cadeia_ok = True
for x in cur.fetchall():
    print(f"   {x['points']:>5}  -> saldo {x['saldo_apos']:>4}   [{x['action_type']}] {x['reason']}")
    if x["saldo_apos"] is None:
        cadeia_ok = False
print(f"   -> {'OK, todo lancamento tem saldo_apos' if cadeia_ok else '<<< FALHOU'}")
TODAS.append(cadeia_ok)

print(); print("=" * 74); print("5) REGRESSAO: salvar o perfil nao pode mexer no saldo"); print("=" * 74)
with get_db_context() as db:
    _movimentar_dcash(db, TESTE, 45, "Login diario simulado", "login_diario")
    db.commit()
antes = saldo()
print(f"   saldo antes de salvar o perfil: {antes}")
print("   (ProfilePage.jsx reenvia points: user.points de um objeto em cache)")
payload = {"name":"Teste Ledger","initials":"TL","role":"Teste","dept":"TI",
           "level":"JR","color":"av-gold","access_level":3,
           "is_admin":False,"is_admin_user":False,"is_rh":False,"is_ouvidor":False,
           "is_diretor":False,"is_leader":False,"nivel_dourado":False,
           "points": 999999,          # <- valor obsoleto do "cache" do navegador
           "hire_date":"2026-01-01","org_position":"colaborador","is_orcoma":False}
r = client.put(f"/api/users/{TESTE}", json=payload, headers=H)
print(f"   PUT /api/users/{TESTE} -> HTTP {r.status_code}")
print(f"   saldo depois: {saldo()}  (esperado {antes}, apesar de points:999999 no payload)")
ok = r.status_code == 200 and saldo() == antes
print(f"   -> {'PASSOU: perfil nao mexeu no saldo' if ok else '<<< FALHOU'}")
TODAS.append(ok)

print(); print("=" * 74); print("6) Endpoint de ajuste de saldo (admin) e ledgerizado"); print("=" * 74)
r = client.put(f"/api/users/{TESTE}/points", json={"points": 100}, headers=H)
print(f"   PUT /api/users/{TESTE}/points -> HTTP {r.status_code}")
print(f"   saldo={saldo()} (esperado 100)")
TODAS.append(r.status_code == 200 and saldo() == 100)
TODAS.append(confere("ledger apos ajuste manual"))

print(); print("=" * 74); print("7) Auditoria: todos batem?"); print("=" * 74)
r = client.get("/api/gamificacao/dcash/auditoria", headers=H)
d = r.json()
meu = [i for i in d["itens"] if i["key"] == TESTE][0]
print(f"   meu item: {meu}")
TODAS.append(meu["confere"])
print(f"\n   (o resto da base ainda diverge ate rodar a ancoragem)")

print(); print("=" * 74); print("8) Ancoragem idempotente e SEM mexer no saldo"); print("=" * 74)
# Trava: guarda o saldo de todo mundo antes da ancoragem. A ancoragem registra
# a divergencia no ledger; ela nao pode criar nem destruir D-Cash de ninguem.
snapshot = {}
cur.execute("SELECT key, COALESCE(points,0) p FROM users")
for r in cur.fetchall():
    snapshot[r["key"]] = r["p"]

r = client.post("/api/gamificacao/dcash/ancorar", headers=H)
print(f"   1a chamada: {r.json()}")
r = client.post("/api/gamificacao/dcash/ancorar", headers=H)
seg = r.json()
print(f"   2a chamada: {seg}")
ok = seg["ancorados"] == 0 and seg["ja_ancorados"] > 0
print(f"   -> {'PASSOU: 2a chamada nao ancora ninguem' if ok else '<<< FALHOU'}")
TODAS.append(ok)

mudou = []
cur.execute("SELECT key, COALESCE(points,0) p FROM users")
for r2 in cur.fetchall():
    if r2["key"] in snapshot and snapshot[r2["key"]] != r2["p"]:
        mudou.append((r2["key"], snapshot[r2["key"]], r2["p"]))
print(f"   saldos alterados pela ancoragem: {len(mudou)}")
for k, a, b in mudou:
    print(f"      {k:<18} {a} -> {b}")
TODAS.append(len(mudou) == 0)

print(); print("=" * 74); print("9) Auditoria depois da ancoragem"); print("=" * 74)
r = client.get("/api/gamificacao/dcash/auditoria", headers=H)
d = r.json()
print(f"   total_usuarios={d['total_usuarios']}  divergentes={d['divergentes']}  "
      f"total_divergencia={d['total_divergencia']}")
if d["divergentes"]:
    for i in d["itens"]:
        if not i["confere"]:
            print(f"      DIVERGENTE {i['key']:<14} {i['name'][:20]:<20} saldo={i['saldo']:>4} ledger={i['ledger']:>4} dif={i['divergencia']:>5}")
TODAS.append(d["ok"])
print(f"   -> {'PASSOU: base inteira reconciliada' if d['ok'] else 'FALHOU'}")

print(); print("=" * 74); print("RESULTADO"); print("=" * 74)
print(f"   {sum(1 for x in TODAS if x)}/{len(TODAS)} verificacoes OK")
TODAS.append(True) if False else None
falhas = [i for i, x in enumerate(TODAS) if not x]
print(f"   falhas nos indices: {falhas if falhas else 'nenhuma'}")

print(); print("=" * 74); print("Limpeza"); print("=" * 74)
limpar()
cur.execute("SELECT COUNT(*) n FROM users WHERE key=%s", (TESTE,))
print(f"   users restantes: {cur.fetchone()['n']}")
conn.close()
