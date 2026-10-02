"""Reparo 2: desfaz a 2a ancoragem errada e fixa os saldos nos valores verificados.

A 2a versao da ancoragem passou a diferenca como delta em _movimentar_dcash, e o
GREATEST(0, ...) do clamp zerou quem tinha saldo baixo. Os saldos corretos sao os
mesmos confirmados no reparo 1 (que bateu com a auditoria inicial).
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

# Saldos verificados: iguais a auditoria inicial, mais o login legitimo de 02/10
# que a Parte 2 passou a creditar (gabriel).
VERIFICADO = {
    "paula": 100, "tatiane": 90, "malu": 40, "bot_diretor": 10, "bot_colaborador": 30,
    "gabriel": 120, "rosana": 190, "arlane": 30, "juliana": 10, "tairla": 30,
    "bot_lider": 0, "cleo": 0, "daiane": 0, "fabiana": 0, "maria paula": 0,
}

print("=" * 78); print("1) Removendo as linhas de abertura (as duas ancoragens erradas)"); print("=" * 78)
cur.execute("SELECT id, user_key, points, reason FROM user_points WHERE action_type='abertura' ORDER BY created_at")
linhas = cur.fetchall()
for l in linhas:
    print(f"   {l['user_key']:<18} {l['points']:>6}  {l['reason'][:64]}")
cur.execute("DELETE FROM user_points WHERE action_type='abertura'")
print(f"   -> {cur.rowcount} linha(s) removida(s)")
conn.commit()

print(); print("=" * 78); print("2) Restaurando os saldos verificados"); print("=" * 78)
cur.execute("SELECT key, COALESCE(points,0) p FROM users")
atual = {r["key"]: r["p"] for r in cur.fetchall()}
for k, alvo in VERIFICADO.items():
    if k not in atual:
        print(f"   {k:<18} USUARIO NAO EXISTE")
        continue
    if atual[k] != alvo:
        cur.execute("UPDATE users SET points=%s WHERE key=%s", (alvo, k))
        print(f"   {k:<18} {atual[k]:>5} -> {alvo:<5} CORRIGIDO")
    else:
        print(f"   {k:<18} {atual[k]:>5} (ja estava certo)")
conn.commit()

print(); print("=" * 78); print("3) Conference final"); print("=" * 78)
cur.execute("""SELECT u.key, COALESCE(u.points,0) saldo, COALESCE(SUM(up.points),0) ledger
               FROM users u LEFT JOIN user_points up ON up.user_key=u.key
               GROUP BY u.key, u.points ORDER BY u.key""")
ok = True
for r in cur.fetchall():
    esp = VERIFICADO.get(r["key"])
    bate = (esp == r["saldo"])
    if not bate:
        ok = False
    print(f"   {r['key']:<18} saldo={r['saldo']:>5}  ledger={r['ledger']:>5}  "
          f"dif={r['saldo']-r['ledger']:>6}  saldo_confere={'sim' if bate else 'NAO'}")
print(f"\n   -> {'TODOS OS SALDOS CORRETOS' if ok else '<<< AINDA DIVERGE'}")

print(); print("=" * 78); print("4) Nenhum lancamento de teste sobrou?"); print("=" * 78)
cur.execute("SELECT COUNT(*) n FROM users WHERE key LIKE 'ZZ_TESTE%'")
print(f"   usuarios de teste: {cur.fetchone()['n']}")
cur.execute("SELECT COUNT(*) n FROM user_points WHERE user_key LIKE 'ZZ_TESTE%'")
print(f"   lancamentos de teste: {cur.fetchone()['n']}")
cur.execute("SELECT COUNT(*) n FROM notifications WHERE target_user_key LIKE 'ZZ_TESTE%'")
print(f"   notificacoes de teste: {cur.fetchone()['n']}")

conn.commit()
conn.close()
