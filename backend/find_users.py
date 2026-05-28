import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("SELECT key, name FROM users ORDER BY key")
for r in cur.fetchall():
    print(repr(r[0]), repr(r[1]))
cur.close()
conn.close()
