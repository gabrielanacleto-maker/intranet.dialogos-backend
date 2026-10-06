# -*- coding: utf-8 -*-
"""Carga inicial de Atendimentos e Descontos Bradescos.

Idempotente: nao duplica registros que ja existam com a mesma
Especialidade Liberada (comparacao sem diferenciar maiusculas/espacos).
Uso: python scripts/seed_atendimentos_bradesco.py
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

# (especialidades_liberadas, guias, desconto_bradesco, valor_profissional)
ROWS = [
    ("ANGIOLOGISTA C/ RETORNO", "2", 0, 170.00),
    ("DOPPLER DAS CAROTIDAS", "40901408", 0, 130.00),
    ("DOPPLER DOS MEMBROS INFERIORES - UNILATERAL ARTERIAL (40901495) "
     "LANÇAR DUAS VEZES + VENOSO (40901483) LANÇAR DUAS VEZES", "", 0, 195.00),
    ("CARDIOLOGISTA C/ RETORNO", "2", 0, 170.00),
    ("CLINICO GERAL S/ RETORNO", "1", 0, 83.76),
    ("LIMPEZA DE PELE", "1", 0, 83.76),
    ("MASSAGEM", "1", 0, 83.76),
    ("NUTRICIONISTA (CONSULTA + BIO) C/ RETORNO", "2", 0, 0),
    ("NUTRICIONISTA (CONSULTA) C/ RETORNO", "2", 0, 0),
    ("RETIRADA DE CERUME (OTORRINO)", "", 0, 20.79),
    ("RETIRADA DE CORPO ESTRANHO (OTORRINO)", "30402042 (UNILATERAL)", 0, 104.74),
    ("NASOFIBROSCOPIA (OTORRINO)", "40201252", 0, 95.44),
    ("REUMATOLOGISTA C/ RETORNO", "2", 0, 170.00),
    ("PSIQUIATRA - DR EDMUNDO", "2", 0, 170.00),
    ("NEUROCIRUGIÃO S/ RETORNO", "1", 0, 83.76),
    ("PEDIATRA S/ RETORNO", "2", 0, 167.00),
    ("PSICOLOGOS ADULTO (5 ATENDIMENTOS)", "5 SESSÕES + 01 MÉDICA", 0, 300.00),
    ("PSICOLOGO INFANTIL (5 ATENDIMENTOS)", "5 SESSÕES + 02 MÉDICA", 0, 300.00),
    ("AURICULOACUPUNTURA", "1", 0, 83.00),
]


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COALESCE(MAX(position_order), 0) AS m FROM atendimentos_bradesco")
            proxima = int(cur.fetchone()["m"]) + 1

            inseridos, ignorados = 0, 0
            for i, (especialidade, guias, desconto, valor) in enumerate(ROWS):
                especialidade = especialidade.strip()
                cur.execute(
                    """SELECT id FROM atendimentos_bradesco
                       WHERE LOWER(TRIM(especialidades_liberadas)) = LOWER(%s)""",
                    (especialidade,),
                )
                if cur.fetchone():
                    ignorados += 1
                    print(f"  = {especialidade[:52]} (ja existe)")
                    continue

                cur.execute(
                    """INSERT INTO atendimentos_bradesco
                       (id, especialidades_liberadas, guias, desconto_bradesco,
                        valor_profissional, position_order, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (str(uuid.uuid4()), especialidade, guias, desconto, valor,
                     proxima + i, datetime.datetime.utcnow().isoformat()),
                )
                inseridos += 1
                print(f"  + {especialidade[:52]}")

        conn.commit()
        print(f"\nInseridos: {inseridos} | Ignorados: {ignorados}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
