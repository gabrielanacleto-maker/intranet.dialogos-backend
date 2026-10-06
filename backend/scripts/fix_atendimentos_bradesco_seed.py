# -*- coding: utf-8 -*-
"""Remove duplicatas da carga inicial e corrige acentuacao."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from database import DB_URL  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

# Especialidades que o usuario ja havia cadastrado manualmente (Title Case).
# As versoes em CAIXA ALTA vindas do seed sao duplicatas e vao ser removidas.
DUPLICATAS = [
    "ANGIOLOGISTA C/ RETORNO",
    "DOPPLER DAS CAROTIDAS",
    "DOPPLER DOS MEMBROS INFERIORES - UNILATERAL ARTERIAL (40901495) "
    "LANCAR DUAS VEZES + VENOSO (40901483) LANCAR DUAS VEZES",
]

# Correcoes de acentuacao (o seed original foi escrito sem acentos).
CORRECOES = [
    ("NEUROCIRURGIAO S/ RETORNO", "NEUROCIRUGIÃO S/ RETORNO", None),
    ("PSICOLOGOS ADULTO (5 ATENDIMENTOS)", None, "5 SESSÕES + 01 MÉDICA"),
    ("PSICOLOGO INFANTIL (5 ATENDIMENTOS)", None, "5 SESSÕES + 02 MÉDICA"),
]


def main():
    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for dup in DUPLICATAS:
                cur.execute(
                    """DELETE FROM atendimentos_bradesco
                       WHERE TRIM(especialidades_liberadas) = %s""",
                    (dup,),
                )
                print(f"  - removida: {dup[:55]} ({cur.rowcount})")

            for especialidade, novo_nome, novas_guias in CORRECOES:
                cur.execute(
                    """UPDATE atendimentos_bradesco
                       SET especialidades_liberadas = COALESCE(%s, especialidades_liberadas),
                           guias = COALESCE(%s, guias)
                       WHERE TRIM(especialidades_liberadas) = %s""",
                    (novo_nome, novas_guias, especialidade),
                )
                print(f"  ~ acentuacao: {especialidade[:45]} ({cur.rowcount})")

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
