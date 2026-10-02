"""Teste do login diario: trava por dia, credito, ledger e notificacao.

Roda contra o banco real. Cria um usuario de teste descartavel, exercita o
endpoint /api/presence/heartbeat varias vezes e confere que o premio acontece
UMA vez. Depois apaga tudo que criou.
"""
import os, sys, uuid, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
from database import init_db
from auth import hash_password, create_token

load_dotenv()
print("Rodando init_db()...")
init_db()
print("init_db() OK\n")

BRT = datetime.timezone(datetime.timedelta(hours=-3))
HOJE = datetime.datetime.now(BRT).date()
TESTE = "ZZ_TESTE_LOGIN"

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def limpar():
    cur.execute("DELETE FROM daily_rewards WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM user_points   WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM notifications WHERE target_user_key=%s", (TESTE,))
    cur.execute("DELETE FROM presence      WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM users         WHERE key=%s", (TESTE,))

limpar()

# usuario de teste
cur.execute("""INSERT INTO users (key, name, initials, role, dept, level, color,
               access_level, points, password_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (TESTE, "Teste Login Diario", "TL", "Teste", "TI", "JR", "av-gold", 1, 0,
             hash_password("Teste@12345")))
print(f"usuario {TESTE} criado com saldo 0\n")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
token = create_token({"sub": TESTE, "role": "user"})
H = {"Authorization": f"Bearer {token}"}

def saldo():
    cur.execute("SELECT COALESCE(points,0) p FROM users WHERE key=%s", (TESTE,))
    return cur.fetchone()["p"]

def premios():
    cur.execute("SELECT COUNT(*) n, COALESCE(SUM(points),0) s FROM daily_rewards WHERE user_key=%s", (TESTE,))
    return cur.fetchone()

def lancamentos():
    cur.execute("SELECT COUNT(*) n, COALESCE(SUM(points),0) s FROM user_points WHERE user_key=%s", (TESTE,))
    return cur.fetchone()

def notifs():
    cur.execute("SELECT type, title, message, target_user_key FROM notifications WHERE target_user_key=%s", (TESTE,))
    return cur.fetchall()

print("=" * 70)
print("1) Tres heartbeats seguidos (o App.jsx chama ao abrir e a cada 60s)")
print("=" * 70)
for i in (1, 2, 3):
    r = client.post("/api/presence/heartbeat", headers=H)
    d = premios()
    print(f"   heartbeat #{i}: HTTP {r.status_code}  saldo={saldo():>3}  premios={d['n']}  ledger={lancamentos()['n']}")

d = premios()
print(f"\n   esperado: 1 premio, saldo 10, 1 lancamento no ledger")
print(f"   obtido  : {d['n']} premio(s), saldo {saldo()}, {lancamentos()['n']} lancamento(s)")
ok = d["n"] == 1 and saldo() == 10 and lancamentos()["n"] == 1
print(f"   -> {'PASSOU' if ok else 'FALHOU'}")

print()
print("=" * 70)
print("2) Notificacao de D-Cash")
print("=" * 70)
ns = notifs()
print(f"   notificacoes geradas: {len(ns)}")
for n in ns:
    print(f"      type={n['type']}  target={n['target_user_key']}  title={n['title']!r}  message={n['message']!r}")
ok = len(ns) == 1 and ns[0]["type"] == "dcash"
print(f"   -> {'PASSOU (1 notificacao, type=dcash)' if ok else 'FALHOU'}")

print()
print("=" * 70)
print("3) INSERT direto na trava (PK deve estourar)")
print("=" * 70)
try:
    cur.execute("""INSERT INTO daily_rewards (user_key,dia_brt,reward_key,points,ledger_id,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (TESTE, HOJE, "login_diario", 10, str(uuid.uuid4()),
                 datetime.datetime.utcnow().isoformat()))
    print("   FALHOU: banco aceitou o mesmo dia")
except psycopg2.errors.UniqueViolation as e:
    print(f"   UniqueViolation (ok): {str(e).splitlines()[0]}")

print()
print("=" * 70)
print("4) Recompensa diferente no mesmo dia (nao deve colidir com login_diario)")
print("=" * 70)
cur.execute("""INSERT INTO daily_rewards (user_key,dia_brt,reward_key,points,ledger_id,created_at)
               VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (TESTE, HOJE, "outro_premio", 5, str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
cur.execute("SELECT COUNT(*) n FROM daily_rewards WHERE user_key=%s AND dia_brt=%s", (TESTE, HOJE))
print(f"   premios hoje: {cur.fetchone()['n']}  -> {'PASSOU (2, chaves distintas)' if cur.fetchone else ''}")
cur.execute("SELECT reward_key, points FROM daily_rewards WHERE user_key=%s ORDER BY reward_key", (TESTE,))
print("   ->", [dict(r) for r in cur.fetchall()])

print()
print("=" * 70)
print("5) Ligacao daily_rewards.ledger_id -> user_points.id")
print("=" * 70)
cur.execute("""SELECT d.reward_key, d.points AS premio, d.ledger_id, p.id AS ledger,
                      p.reason, p.action_type
               FROM daily_rewards d
               LEFT JOIN user_points p ON p.id = d.ledger_id
               WHERE d.user_key=%s ORDER BY d.reward_key""", (TESTE,))
for r in cur.fetchall():
    bate = "ok" if r["ledger"] == r["ledger_id"] else "sem ledger (inserido direto, fora do helper)"
    print(f"   {r['reward_key']:<14} premio={r['premio']} ledger_id={r['ledger_id'][:8]}… "
          f"user_points.id={str(r['ledger'])[:8]}… [{bate}]")
    print(f"      reason={r['reason']!r} action_type={r['action_type']!r}")
print("   esperado: login_diario com ledger preenchido; outro_premio sem ledger,")
print("   porque o teste o inseriu direto na tabela, sem passar por _premiar_dcash_diario.")

print()
print("=" * 70)
print("6) Limpeza")
print("=" * 70)
limpar()
cur.execute("""SELECT
    (SELECT COUNT(*) FROM users         WHERE key=%s) u,
    (SELECT COUNT(*) FROM daily_rewards WHERE user_key=%s) d,
    (SELECT COUNT(*) FROM user_points   WHERE user_key=%s) p,
    (SELECT COUNT(*) FROM notifications WHERE target_user_key=%s) n""",
            (TESTE, TESTE, TESTE, TESTE))
r = cur.fetchone()
print(f"   users={r['u']} daily_rewards={r['d']} user_points={r['p']} notifications={r['n']}")
print(f"   -> {'TUDO REMOVIDO' if sum(r.values()) == 0 else 'SOBROU LIXO'}")
conn.close()
