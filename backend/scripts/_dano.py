import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
load_dotenv()
c=psycopg2.connect(os.getenv("DATABASE_URL")); c.autocommit=True
cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("== linhas 'abertura' criadas pelo teste (o estrago) ==")
cur.execute("""SELECT user_key, points, saldo_apos, created_at FROM user_points
               WHERE action_type='abertura' ORDER BY user_key""")
anch = cur.fetchall()
for r in anch:
    antes = r["saldo_apos"] - r["points"]
    print(f"   {r['user_key']:<18} delta=+{r['points']:<5} saldo_apos={r['saldo_apos']:<5} "
          f"=> saldo_antes_do_ancor={antes:<5} em {r['created_at'][:19]}")
print(f"   total: {len(anch)} linhas")

print()
print("== estado ATUAL de cada usuario ==")
cur.execute("""SELECT u.key, COALESCE(u.points,0) saldo,
                      COALESCE(SUM(up.points),0) ledger
               FROM users u LEFT JOIN user_points up ON up.user_key=u.key
               GROUP BY u.key, u.points ORDER BY u.key""")
for r in cur.fetchall():
    print(f"   {r['key']:<18} saldo={r['saldo']:>5}  ledger={r['ledger']:>5}  dif={r['saldo']-r['ledger']:>6}")

print()
print("== lancamentos NAO-anertura de hoje (logins legítimos da Parte 2) ==")
cur.execute("""SELECT user_key, action_type, points, created_at FROM user_points
               WHERE action_type NOT IN ('abertura') AND created_at >= '2026-10-01'
               ORDER BY created_at""")
rows = cur.fetchall()
for r in rows:
    print(f"   {r['created_at'][:19]}  {r['user_key']:<18} {r['points']:>4}  [{r['action_type']}]")
print(f"   total: {len(rows)}")
c.close()
