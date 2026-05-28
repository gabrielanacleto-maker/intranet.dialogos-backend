import sys, os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
senha = sys.stdin.readline().strip()
from auth import hash_password
h = hash_password(senha)

users = ['arlane', 'tatiane', 'maria paula', 'cleo', 'juliana']
for u in users:
    cur.execute("UPDATE users SET password_hash=%s, password_changed=0 WHERE key=%s", (h, u))
    if cur.rowcount:
        print(f"OK: {u}")
    else:
        print(f"NÃO ENCONTRADO: {u}")
conn.commit()
cur.close()
conn.close()
