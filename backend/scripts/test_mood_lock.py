"""Teste da trava de humor: verifica a PK (user_key, dia_brt) no banco real."""
import os, sys, datetime, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
from database import init_db

load_dotenv()
print("Rodando init_db()...")
init_db()
print("init_db() OK\n")

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

TESTE = "ZZ_TESTE_TRAVA"
hoje = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3))).date()
print(f"usuario de teste: {TESTE}   dia BRT: {hoje}\n")

def limpar():
    cur.execute("DELETE FROM mood_daily_lock WHERE user_key=%s", (TESTE,))
    cur.execute("DELETE FROM mood_history WHERE user_key=%s", (TESTE,))
limpar()

print("1) Primeira inserção (deve aceitar):")
cur.execute("""INSERT INTO mood_daily_lock (user_key,dia_brt,mood,mood_id,created_at)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_key,dia_brt) DO NOTHING""",
            (TESTE, hoje, "feliz", str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
print(f"   rowcount={cur.rowcount}  -> {'ACEITOU (ok)' if cur.rowcount==1 else 'FALHOU'}")

print("\n2) Segunda inserção no MESMO dia (deve recusar):")
cur.execute("""INSERT INTO mood_daily_lock (user_key,dia_brt,mood,mood_id,created_at)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_key,dia_brt) DO NOTHING""",
            (TESTE, hoje, "triste", str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
print(f"   rowcount={cur.rowcount}  -> {'RECUSOU (ok)' if cur.rowcount==0 else 'FALHOU: aceitou 2x'}")

print("\n3) INSERT direto SEM ON CONFLICT (a PK deve estourar):")
try:
    cur.execute("""INSERT INTO mood_daily_lock (user_key,dia_brt,mood,mood_id,created_at)
                   VALUES (%s,%s,%s,%s,%s)""",
                (TESTE, hoje, "neutro", str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
    print("   FALHOU: banco aceitou duplicata")
except psycopg2.errors.UniqueViolation as e:
    print(f"   UniqueViolation (ok): {str(e).splitlines()[0]}")

print("\n4) Usuario NOVO, mesmo dia (deve aceitar - trava e por usuario):")
cur.execute("""INSERT INTO mood_daily_lock (user_key,dia_brt,mood,mood_id,created_at)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_key,dia_brt) DO NOTHING""",
            (TESTE+"_2", hoje, "feliz", str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
print(f"   rowcount={cur.rowcount}  -> {'ACEITOU (ok)' if cur.rowcount==1 else 'FALHOU'}")

print("\n5) Dia ANTERIOR (deve aceitar - trava e por dia):")
ontem = hoje - datetime.timedelta(days=1)
cur.execute("""INSERT INTO mood_daily_lock (user_key,dia_brt,mood,mood_id,created_at)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_key,dia_brt) DO NOTHING""",
            (TESTE, ontem, "feliz", str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
print(f"   rowcount={cur.rowcount}  -> {'ACEITOU (ok)' if cur.rowcount==1 else 'FALHOU'}")

print("\n6) Reset: apaga SO o dia de hoje e devolve a chave:")
cur.execute("SELECT mood_id, dia_brt FROM mood_daily_lock WHERE user_key=%s ORDER BY dia_brt", (TESTE,))
antes = cur.fetchall()
print(f"   antes: {len(antes)} registro(s) -> {[str(r['dia_brt']) for r in antes]}")
alvo = [r for r in antes if r["dia_brt"] == hoje][0]
cur.execute("DELETE FROM mood_history WHERE id=%s", (alvo["mood_id"],))
cur.execute("DELETE FROM mood_daily_lock WHERE user_key=%s AND dia_brt=%s", (TESTE, hoje))
cur.execute("SELECT mood_id, dia_brt FROM mood_daily_lock WHERE user_key=%s", (TESTE,))
depois = cur.fetchall()
print(f"   depois: {len(depois)} registro(s) -> {[str(r['dia_brt']) for r in depois]}")
print(f"   -> {'HISTORICO PRESERVADO (ok)' if [str(r['dia_brt']) for r in depois]==[str(ontem)] else 'FALHOU'}")

print("\n7) Reset libera o dia de hoje (deve aceitar de novo):")
cur.execute("""INSERT INTO mood_daily_lock (user_key,dia_brt,mood,mood_id,created_at)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_key,dia_brt) DO NOTHING""",
            (TESTE, hoje, "muito_feliz", str(uuid.uuid4()), datetime.datetime.utcnow().isoformat()))
print(f"   rowcount={cur.rowcount}  -> {'ACEITOU (ok)' if cur.rowcount==1 else 'FALHOU'}")

# limpeza
cur.execute("DELETE FROM mood_daily_lock WHERE user_key IN (%s,%s)", (TESTE, TESTE+"_2"))
cur.execute("DELETE FROM mood_history WHERE user_key IN (%s,%s)", (TESTE, TESTE+"_2"))
print("\nDados de teste removidos.")

print("\n8) INTEGRIDADE: historico existente nao foi tocado")
cur.execute("SELECT COUNT(*) n FROM mood_history")
print(f"   mood_history: {cur.fetchone()['n']} registros (esperado: 97, igual a antes da parte 1)")
cur.execute("""SELECT COUNT(*) n FROM (SELECT user_key, LEFT(created_at,10) d FROM mood_history
                              GROUP BY user_key, LEFT(created_at,10) HAVING COUNT(*)>1) t""")
print(f"   usuario/dia com >1 resposta: {cur.fetchone()['n']} (esperado: 16, historico preservado)")
conn.close()
