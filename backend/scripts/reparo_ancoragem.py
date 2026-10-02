"""Reparo: desfaz a ancoragem que somava o saldo em vez de registrar a diferenca.

A ancoragem errada criou linhas action_type='abertura' com points = saldo, o que
AUMENTOU o saldo de 10 usuarios. Cada linha carrega o valor exato que aplicou
(saldo_apos - points = saldo antes da ancoragem), entao a reversao e exata.

Nao toca em nenhum outro lancamento: os logins legitimos da Parte 2 permanecem.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import psycopg2, psycopg2.extras
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
conn.autocommit = False
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print("=" * 78)
print("1) Estado ANTES do reparo")
print("=" * 78)
cur.execute("""SELECT u.key, COALESCE(u.points,0) saldo, COALESCE(SUM(up.points),0) ledger
               FROM users u LEFT JOIN user_points up ON up.user_key=u.key
               GROUP BY u.key, u.points ORDER BY u.key""")
antes = {r["key"]: r for r in cur.fetchall()}
for k, r in antes.items():
    print(f"   {k:<18} saldo={r['saldo']:>5}  ledger={r['ledger']:>5}")

print()
print("=" * 78)
print("2) Reversao: cada linha 'abertura' e desfeita (saldo e ledger)")
print("=" * 78)
cur.execute("SELECT id, user_key, points, saldo_apos FROM user_points WHERE action_type='abertura'")
linhas = cur.fetchall()
for l in linhas:
    antes_do_ancor = l["saldo_apos"] - l["points"]
    cur.execute("UPDATE users SET points=%s WHERE key=%s", (antes_do_ancor, l["user_key"]))
    cur.execute("DELETE FROM user_points WHERE id=%s", (l["id"],))
    print(f"   {l['user_key']:<18} desfeito: -{l['points']:<5} (saldo volta a {antes_do_ancor})")
conn.commit()
print(f"\n   {len(linhas)} linha(s) de abertura removida(s).")

print()
print("=" * 78)
print("3) Estado DEPOIS do reparo (antes de ancorar de novo)")
print("=" * 78)
cur.execute("""SELECT u.key, COALESCE(u.points,0) saldo, COALESCE(SUM(up.points),0) ledger
               FROM users u LEFT JOIN user_points up ON up.user_key=u.key
               GROUP BY u.key, u.points ORDER BY u.key""")
depois = {r["key"]: r for r in cur.fetchall()}
for k, r in depois.items():
    d = r["saldo"] - r["ledger"]
    print(f"   {k:<18} saldo={r['saldo']:>5}  ledger={r['ledger']:>5}  dif={d:>6}")

print()
print("=" * 78)
print("4) Conference contra a auditoria inicial (antes de qualquer mudanca)")
print("=" * 78)
# Saldos registrados na primeira auditoria, antes das Partes 1/2/3.
ESPERADO = {
    "paula": 100, "tatiane": 90, "malu": 40, "bot_diretor": 10, "bot_colaborador": 30,
    "gabriel": 110, "rosana": 190, "arlane": 30, "juliana": 10, "tairla": 30,
    "bot_lider": 0, "cleo": 0, "daiane": 0, "fabiana": 0, "maria paula": 0,
}
confere = True
for k, esp in ESPERADO.items():
    real = depois.get(k, {}).get("saldo", None)
    if k == "gabriel":
        nota = "  (110 + 10 do login legitimo de hoje = 120)"
        ok = real == 120
    else:
        nota = ""
        ok = real == esp
    if not ok:
        confere = False
    print(f"   {k:<18} esperado={esp:>4}  real={str(real):>4}  {'OK' if ok else '<<< DIVERGE'}{nota}")
print(f"\n   -> {'TODOS OS SALDOS CORRETOS' if confere else '<<< AINDA DIVERGE'}")

conn.commit()
conn.close()
