# -*- coding: utf-8 -*-
""" Especialidades com desconto Bradesco (o DESCONTO entra na coluna
Descontos Bradesco). Idempotente: nao duplica especialidades ja existentes.
Uso: python scripts/seed_descontos_bradesco_pct.py
"""
import os
import sys
import uuid
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from database import DB_URL  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

# (especialidades_liberadas, guias, desconto_bradesco, desconto_bradesco_pct, valor_profissional)
ROWS = [
    ("OTORRINO", "", 10, True, 220.50),
    ("ENDOCRINOLOGISTA", "", 10, True, 250.00),
    ("UROLOGISTA", "", 10, True, 252.00),
    ("NEUROLOGISTA", "", 10, True, 252.00),
]


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(position_order), 0) AS m FROM atendimentos_bradesco")
            proxima = int(cur.fetchone()["m"]) + 1

            inseridos, ignorados = 0, 0
            for i, (especialidade, guias, desconto, pct, valor) in enumerate(ROWS):
                especialidade = especialidade.strip()
                cur.execute(
                    """SELECT id FROM atendimentos_bradesco
                       WHERE LOWER(TRIM(especialidades_liberadas)) = LOWER(%s)""",
                    (especialidade,),
                )
                if cur.fetchone():
                    ignorados += 1
                    print(f"  = {especialidade} (ja existe)")
                    continue

                cur.execute(
                    """INSERT INTO atendimentos_bradesco
                       (id, especialidades_liberadas, guias, desconto_bradesco,
                        desconto_bradesco_pct, valor_profissional, position_order, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (str(uuid.uuid4()), especialidade, guias, desconto, pct, valor,
                     proxima + i, datetime.datetime.utcnow().isoformat()),
                )
                inseridos += 1
                print(f"  + {especialidade} | {desconto}% | R$ {valor:.2f}")

        conn.commit()
        print(f"\nInseridos: {inseridos} | Ignorados: {ignorados}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
