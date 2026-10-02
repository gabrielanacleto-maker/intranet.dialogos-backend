"""Teste do premio de humor: 1 por dia, e reset nao paga de novo.

Usa usuario descartavel. Cobre o caminho que o MoodWidget usa: POST /api/mood.
"""
import os, sys, uuid, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
from database import init_db
from auth import hash_password, create_token

load_dotenv()
init_db()

BRT = datetime.timezone(datetime.timedelta(hours=-3))
HOJE = datetime.datetime.now(BRT).date()
TESTE = "ZZ_TESTE_HUMOR"

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def limpar():
    cur.execute("DELETE FROM daily_rewards  WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM user_points    WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM notifications  WHERE target_user_key=%s", (TESTE,))
    cur.execute("DELETE FROM mood_daily_lock WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM mood_history    WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM users           WHERE key=%s", (TESTE,))

limpar()
cur.execute("""INSERT INTO users (key,name,initials,role,dept,level,color,
               access_level,points,password_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (TESTE,"Teste Humor","TH","Teste","TI","JR","av-gold",2,0,
             hash_password("Teste@12345")))

from fastapi.testclient import TestClient
from main import app
client = TestClient(app)
# access_level 2 para poder usar /api/mood/reset
token = create_token({"sub": TESTE, "role": "user"})
H = {"Authorization": f"Bearer {token}"}

def saldo():
    cur.execute("SELECT COALESCE(points,0) p FROM users WHERE key=%s", (TESTE,))
    return cur.fetchone()["p"]

def n(lab, sql):
    cur.execute(sql, (TESTE,))
    return cur.fetchone()["n"]

print("=" * 70); print("1) POST /api/mood (1a avaliacao de hoje)"); print("=" * 70)
r = client.post("/api/mood", json={"valor_humor": 4}, headers=H)
print(f"   HTTP {r.status_code}  {r.json()}")
print(f"   saldo={saldo()}  premios_humor={n('x','SELECT COUNT(*) n FROM daily_rewards WHERE user_key=%s AND reward_key=%s')}" if False else
      f"   saldo={saldo()}")
cur.execute("SELECT COUNT(*) n, COALESCE(SUM(points),0) s FROM daily_rewards WHERE user_key=%s AND reward_key='humor_diario'", (TESTE,))
d = cur.fetchone()
print(f"   premios humor_diario={d['n']} soma={d['s']}")
print(f"   -> {'PASSOU' if r.status_code == 200 and saldo() == 10 and d['n'] == 1 else 'FALHOU'}")

print(); print("=" * 70); print("2) Segunda avaliacao no mesmo dia (deve dar 429, sem premio)"); print("=" * 70)
r2 = client.post("/api/mood", json={"valor_humor": 2}, headers=H)
cur.execute("SELECT COUNT(*) n FROM daily_rewards WHERE user_key=%s AND reward_key='humor_diario'", (TESTE,))
d2 = cur.fetchone()
print(f"   HTTP {r2.status_code}  detalhe={r2.json().get('detail')!r}")
print(f"   saldo={saldo()}  premios humor_diario={d2['n']}")
print(f"   -> {'PASSOU (429 e sem premio extra)' if r2.status_code == 429 and saldo() == 10 else 'FALHOU'}")

print(); print("=" * 70); print("3) GET /api/mood/status"); print("=" * 70)
r3 = client.get("/api/mood/status", headers=H)
print(f"   {r3.json()}")

print(); print("=" * 70); print("4) Reset do humor (admin) e NOVA avaliacao"); print("=" * 70)
r4 = client.post("/api/mood/reset", headers=H)
print(f"   reset -> HTTP {r4.status_code} {r4.json()}")
cur.execute("SELECT COUNT(*) n FROM mood_history WHERE user_key=%s", (TESTE,))
print(f"   respostas no historico apos o reset: {cur.fetchone()['n']}  (tem que ser 0: o reset apaga SO o dia)")
r5 = client.post("/api/mood", json={"valor_humor": 5}, headers=H)
cur.execute("SELECT COUNT(*) n FROM daily_rewards WHERE user_key=%s AND reward_key='humor_diario'", (TESTE,))
d5 = cur.fetchone()
print(f"   nova avaliacao -> HTTP {r5.status_code}")
print(f"   saldo={saldo()}  premios humor_diario={d5['n']}  <-- deve continuar 1 e saldo 10")
print(f"   -> {'PASSOU (reset liberou o voto, mas NAO pagou D-Cash de novo)' if d5['n'] == 1 and saldo() == 10 else 'FALHOU: pagou duas vezes'}")

print(); print("=" * 70); print("5) Ledger: os lancamentos de humor"); print("=" * 70)
cur.execute("SELECT points, reason, action_type FROM user_points WHERE user_key=%s ORDER BY created_at", (TESTE,))
for x in cur.fetchall():
    print(f"   {x['points']:>4} pts  action_type={x['action_type']!r}  reason={x['reason']!r}")

print(); print("=" * 70); print("6) Notificacoes"); print("=" * 70)
cur.execute("SELECT type, title FROM notifications WHERE target_user_key=%s ORDER BY created_at", (TESTE,))
for x in cur.fetchall():
    print(f"   {x['type']:<8} {x['title']!r}")

print(); print("=" * 70); print("7) Limpeza"); print("=" * 70)
limpar()
cur.execute("""SELECT
  (SELECT COUNT(*) FROM users          WHERE key=%s) u,
  (SELECT COUNT(*) FROM daily_rewards  WHERE user_key=%s) d,
  (SELECT COUNT(*) FROM user_points    WHERE user_key=%s) p,
  (SELECT COUNT(*) FROM notifications  WHERE target_user_key=%s) n,
  (SELECT COUNT(*) FROM mood_history   WHERE user_key=%s) m,
  (SELECT COUNT(*) FROM mood_daily_lock WHERE user_key=%s) l""",
            (TESTE,)*6)
r = cur.fetchone()
print(f"   users={r['u']} daily_rewards={r['d']} user_points={r['p']} notifications={r['n']} mood={r['m']} lock={r['l']}")
print(f"   -> {'TUDO REMOVIDO' if sum(r.values()) == 0 else 'SOBROU LIXO'}")
conn.close()
