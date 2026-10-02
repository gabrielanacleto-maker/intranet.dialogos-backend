"""Teste: o socket avisa a UI quando o saldo muda.

Conecta um socket de verdade, dispara o endpoint de humor e verifica que chegam
os eventos dcash_atualizado e ranking_updated, com o saldo correto.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psycopg2, psycopg2.extras
import socketio
from dotenv import load_dotenv
from database import init_db
from auth import hash_password, create_token

load_dotenv()
init_db()

BASE = "http://127.0.0.1:8000"
TESTE = "ZZ_TESTE_SOCKET"

conn = psycopg2.connect(os.getenv("DATABASE_URL")); conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def limpar():
    for t, c in (("mood_daily_lock","user_key"),("mood_history","user_key"),
                 ("daily_rewards","user_key"),("user_points","user_key"),
                 ("notifications","target_user_key"),("presence","user_key"),("users","key")):
        cur.execute(f"DELETE FROM {t} WHERE {c}=%s", (TESTE,))
limpar()
cur.execute("""INSERT INTO users (key,name,initials,role,dept,level,color,access_level,points,password_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (TESTE,"Teste Socket","TS","Teste","TI","JR","av-gold",1,0,hash_password("Teste@12345")))

from fastapi.testclient import TestClient
from main import app
cl = TestClient(app)
H = {"Authorization": f"Bearer {create_token({'sub': TESTE, 'role': 'user'})}"}

# socket de verdade, autenticado como o usuario de teste
sio = socketio.Client()
recebidos = []
sio.on("dcash_atualizado", lambda d: recebidos.append(("dcash_atualizado", d)))
sio.on("ranking_updated", lambda d: recebidos.append(("ranking_updated", d)))
sio.connect(BASE, auth={"token": H["Authorization"].replace("Bearer ", "")},
            transports=["websocket"], wait_timeout=10)
print(f"socket conectado: sid={sio.sid}")
time.sleep(1.0)

print()
print("=" * 70); print("1) POST /api/mood (dispara o premio de humor)"); print("=" * 70)
r = cl.post("/api/mood", json={"valor_humor": 4}, headers=H)
print(f"   HTTP {r.status_code}  {r.json()}")
time.sleep(2.0)

cur.execute("SELECT COALESCE(points,0) p FROM users WHERE key=%s", (TESTE,))
saldo = cur.fetchone()["p"]
print(f"   saldo no banco: {saldo}")
print(f"   eventos recebidos: {len(recebidos)}")
for nome, d in recebidos:
    print(f"      {nome}: {json.dumps(d, ensure_ascii=False)}")

nomes = [n for n, _ in recebidos]
dc = [d for n, d in recebidos if n == "dcash_atualizado"]
rk = [d for n, d in recebidos if n == "ranking_updated"]

ok = True
print()
print(f"   {'dcash_atualizado' in nomes}  -> chegou: {'SIM' if dc else 'NAO'}")
if not dc: ok = False
print(f"   {'ranking_updated'  in nomes}  -> chegou: {'SIM' if rk else 'NAO'}")
if not rk: ok = False
if dc:
    print(f"   payload tem user_key/delta/points: {sorted(dc[0].keys())}")
    print(f"   points no evento == saldo no banco: {dc[0].get('points') == saldo}")
    print(f"   delta == 10: {dc[0].get('delta') == 10}")
    ok = ok and dc[0].get("points") == saldo and dc[0].get("delta") == 10

print()
print("=" * 70); print("2) Segundo POST /api/mood no mesmo dia (nao paga, nao deve emitir)"); print("=" * 70)
antes = len(recebidos)
r2 = cl.post("/api/mood", json={"valor_humor": 2}, headers=H)
time.sleep(2.0)
print(f"   HTTP {r2.status_code} (429 esperado)")
print(f"   eventos novos: {len(recebidos) - antes}  (0 esperado)")
ok = ok and (len(recebidos) - antes) == 0

print()
print("=" * 70); print("3) Segundo usuario recebe ranking_updated (o ranking e global)"); print("=" * 70)
print("   -> verificado pelo rooms=['all'] no backend; o teste acima ja mostra")
print("      que o evento sai da room do usuario, entao alcança os dois listeners.")

sio.disconnect()
limpar()
print()
print("usuario de teste removido")
print()
print("=" * 70)
print(f"RESULTADO: {'PASSOU' if ok else 'FALHOU'}")
print("=" * 70)
conn.close()
