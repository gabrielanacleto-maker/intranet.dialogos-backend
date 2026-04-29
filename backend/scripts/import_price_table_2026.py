import sqlite3
import uuid
import datetime

DB_PATH = r"C:\dialogos\backend\dialogos.db"


def proc(name, cash, card_pix):
    return {
        "name": name.strip(),
        "value_cash": float(cash) if cash is not None else 0.0,
        "value_card_pix": float(card_pix) if card_pix is not None else 0.0,
        "value_bradesco": 0.0,
        "value_brv": 0.0,
        "value_prefeitura": 0.0,
    }


DATA = [
    {
        "doctor": "Gastroenterologia",
        "procedures": [
            proc("Consulta", 450, 499),
            proc("EDA", 500, 559),
            proc("Colonoscopia (Sem Consulta)", 1650, 1839),
            proc("Retossigmoidoscopia", 1000, 1119),
            proc("Biópsia", 150, 169),
            proc("Teste Resp. de Hidrogênio e Metanol (SIBO e IMO)", 800, 889),
            proc("Teste Resp. de Hidrogênio e Metanol (IMO)", 500, 559),
            proc("Teste Resp. de Hidrogênio (SIBO)", 500, 559),
        ],
    },
    {
        "doctor": "Dermatologia",
        "procedures": [
            proc("Consulta", 450, 499),
            proc("Patch Teste", 600, 670),
            proc("Toxina Botulínica (Rosto Completo e Pescoço)", 1600, 1799),
            proc("Fios de PDO (Estímulo de Colágeno)", 1500, 1699),
            proc("Bioestimulador Sculptra", 3000, 3399),
            proc("Bioestimulador Radiesse", 2500, 2799),
            proc("Preenchimento 1ml", 1500, 1699),
            proc("Preenchimento Labial", 3000, 3399),
            proc("Rinomodelação", 3000, 3399),
            proc("Preenchimento de Olheiras", 1500, 1699),
        ],
    },
    {"doctor": "Pediatria", "procedures": [proc("Consulta", 420, 469)]},
    {"doctor": "Neuropediatria", "procedures": [proc("Consulta", 550, 619)]},
    {
        "doctor": "Angiologia",
        "procedures": [
            proc("Consulta", 280, 319),
            proc("Doppler das Carótidas", 320, 359),
            proc("Doppler dos Membros Inferiores (cada membro)", 350, 389),
        ],
    },
    {
        "doctor": "Cardiologia",
        "procedures": [
            proc("Consulta", 250, 279),
            proc("Combo: Consulta + ECG", 300, 339),
            proc("Ecocardiograma", 330, 369),
        ],
    },
    {"doctor": "Clínico Geral", "procedures": [proc("Consulta", 200, 229)]},
    {"doctor": "Neurocirurgião", "procedures": [proc("Consulta", 1000, 1119)]},
    {
        "doctor": "Medicina do Trabalho",
        "procedures": [
            proc("ASO sem e-Social", 80, 89),
            proc("ASO com e-Social", 100, 119),
        ],
    },
    {
        "doctor": "Otorrino",
        "procedures": [
            proc("Consulta (lavagem de ouvido inclusa)", 350, 389),
            proc("Prick Teste", 300, 339),
            proc("Cauterização química (ouvido e nariz)", 150, 169),
            proc("Nasofibroscopia (videolaringoscopia/endoscopia nasal)", 250, 279),
            proc("Biópsia de lesão (sem análise)", 500, 559),
            proc("Frenotomia (soltar a língua)", 500, 559),
        ],
    },
    {
        "doctor": "Urologia",
        "procedures": [
            proc("Consulta com toque retal", 350, 389),
            proc("Cauterização de lesão a frio (criocauterização)", 500, 559),
            proc("Cauterização de lesão bisturi elétrico", 700, 779),
            proc("Biópsia de próstata local", 1350, 1499),
            proc("Plástica de freio sem sedação", 3860, 4299),
            proc("Postectomia local", 4600, 5299),
            proc("Vasectomia local", 5600, 6299),
            proc("Biópsia de lesão em pênis", 800, 889),
            proc("Biópsia de lesão de bolsa testicular", 800, 889),
            proc("Pequenas (lipoma, cisto, sinal)", 800, 889),
        ],
    },
    {
        "doctor": "Reumatologia",
        "procedures": [
            proc("Consulta", 300, 339),
            proc("Infiltração com Ácido Hialurônico (pg antecipado)", 1500, 1669),
            proc("Infiltração joelho com Triancil", 400, 449),
            proc("BSV - Bloqueio Simpático Venoso", 400, 449),
            proc("Infiltração de ponto-gatilho", 150, 169),
            proc("Tratamento para vasos", 200, 229),
        ],
    },
    {
        "doctor": "Ortopedia Adulto",
        "procedures": [
            proc("Consulta", 300, 339),
            proc("Infiltração com Ácido Hialurônico (pg antecipado)", 1500, 1669),
            proc("Infiltração joelho com Triancil", 400, 449),
            proc("Infiltração ombro/tornozelo/cotovelo/pé/punho/mão com Diprospan", 400, 449),
        ],
    },
    {"doctor": "Ortopedia Criança", "procedures": [proc("Consulta", 350, 389)]},
    {
        "doctor": "Ginecologia",
        "procedures": [
            proc("Consulta", 400, 449),
            proc("Consulta + Preventivo + Colposcopia", 630, 699),
            proc("Preventivo + Colposcopia", 300, 339),
            proc("Colposcopia (somente)", 220, 249),
            proc("Captura híbrida HPV com análise", 400, 449),
            proc("Cauterização colo do útero", 900, 999),
            proc("Biópsia do colo do útero (sem análise)", 550, 619),
            proc("Biópsia vulva/genotipagem com análise", 700, 779),
            proc("Consulta + captura para HPV", 500, 559),
            proc("Consulta + captura para HPV (plano 3x)", 750, 839),
        ],
    },
    {"doctor": "Endocrinologia", "procedures": [proc("Consulta", 360, 399)]},
    {
        "doctor": "Neurologia",
        "procedures": [
            proc("Consulta", 400, 449),
            proc("Consulta com laudo", 500, 559),
        ],
    },
    {"doctor": "Psiquiatria", "procedures": [proc("Consulta", 350, 389)]},
    {
        "doctor": "Psicologia",
        "procedures": [
            proc("1ª Consulta", 180, 199),
            proc("Sessões Individuais", 130, 149),
            proc("Pacote (4 Sessões)", 480, 539),
            proc("Consulta Terapia de Casal", 250, 279),
            proc("Sessão Terapia de Casal", 200, 229),
        ],
    },
    {
        "doctor": "Ultrassonografia",
        "procedures": [
            proc("Abdômen total/superior/inferior e parede abdominal", 200, 229),
            proc("US cervical/pescoço/tireoide/mama/axila/testículo/inguinal/vias urinárias/pélvica/próstata/transvaginal/obstétrica", 150, 169),
            proc("Tireoide com doppler / Transvaginal com doppler", 180, 199),
            proc("Obstétrica com doppler", 250, 279),
            proc("Morfológica 1º trimestre (com doppler + cervicometria)", 450, 499),
            proc("Morfológica 2º trimestre (com doppler + cervicometria)", 600, 669),
            proc("Doppler das Carótidas", 320, 359),
        ],
    },
    {
        "doctor": "Depilação a Laser",
        "procedures": [
            proc("Axila", 100, 119),
            proc("Buço", 70, 79),
            proc("Facial Feminina", 70, 79),
            proc("Facial Masculina", 140, 159),
            proc("Virilha Completa", 180, 199),
            proc("Perna Inteira", 250, 279),
            proc("Perna abaixo do Joelho", 150, 169),
            proc("Coxa", 150, 169),
            proc("Pescoço", 60, 69),
            proc("Axila + Virilha", 260, 289),
            proc("Perna Inteira + Virilha", 410, 459),
            proc("Peito + Abdômen", 200, 229),
            proc("Peito + Abdômen + Costas", 250, 279),
        ],
    },
    {
        "doctor": "Exames",
        "procedures": [
            proc("Eletrocardiograma", 80, 89),
            proc("Mapa/Holter", 250, 279),
            proc("Polissonografia", 250, 279),
        ],
    },
    {
        "doctor": "Nutricionista",
        "procedures": [
            proc("Consulta", 200, 229),
            proc("Bioimpedância", 120, 139),
            proc("Bioimpedância + Dieta", 320, 359),
        ],
    },
    {
        "doctor": "Avaliação Neuropsicológica",
        "procedures": [proc("Avaliação Neuropsicológica", 1800, 1999)],
    },
    {
        "doctor": "Neuropsicopedagoga",
        "procedures": [
            proc("1ª Consulta", 180, 199),
            proc("Sessões Individuais", 100, 115),
            proc("Pacote (4 Sessões)", 360, 399),
        ],
    },
    {
        "doctor": "Musicoterapia",
        "procedures": [
            proc("Consulta", 150, 169),
            proc("Sessão", 100, 115),
        ],
    },
    {
        "doctor": "Fisioterapia Infantil",
        "procedures": [
            proc("Avaliação", 120, 139),
            proc("Sessão", 100, 115),
            proc("Pacote 4 Sessões", 360, 399),
            proc("Liberação Miofascial", 100, 120),
            proc("Ventosa", 100, 115),
        ],
    },
    {
        "doctor": "Fisioterapia Estética",
        "procedures": [
            proc("Auriculoacupuntura (1ª)", 100, 115),
            proc("Auriculoacupuntura (Sessão)", 70, 79),
            proc("Detox Corporal Ortomolecular 3k", 350, 389),
            proc("Drenagem Linfática Manual Corporal", 150, 169),
            proc("Lipoescultura Gessada", 250, 279),
            proc("Ozonioterapia Auricular", 90, 99),
            proc("Ozonioterapia Sistêmica", 150, 169),
            proc("Ozonioterapia para Dor/Reabilitação", 100, 115),
            proc("Terapia Manual", 100, 115),
            proc("Tratamento para Acne", 250, 279),
            proc("Tratamento para Celulite", 250, 0),
            proc("Tratamento para Estrias", 250, 0),
            proc("Tratamento para Gordura Localizada", 250, 0),
            proc("Tratamento para Melasma", 250, 0),
            proc("Microagulhamento Facial", 250, 0),
            proc("Intradermoterapia Facial (sob avaliação)", 0, 0),
            proc("Intradermoterapia Corporal (sob avaliação)", 0, 0),
        ],
    },
]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    folder = cur.execute(
        "SELECT id FROM folders WHERE name LIKE ? LIMIT 1",
        ("%Tabela de Preços%",),
    ).fetchone()
    if not folder:
        raise RuntimeError("Pasta 'Tabela de Preços' não encontrada.")
    folder_id = folder["id"]

    doctor_ids = [
        r["id"]
        for r in cur.execute("SELECT id FROM price_doctors WHERE folder_id=?", (folder_id,)).fetchall()
    ]
    if doctor_ids:
        placeholders = ",".join("?" for _ in doctor_ids)
        cur.execute(f"DELETE FROM price_procedures WHERE doctor_id IN ({placeholders})", doctor_ids)
        cur.execute("DELETE FROM price_doctors WHERE folder_id=?", (folder_id,))

    doctor_count = 0
    proc_count = 0
    now = datetime.datetime.utcnow().isoformat()

    for idx_d, doc in enumerate(DATA):
        doctor_id = str(uuid.uuid4())
        doctor_name = doc["doctor"].strip()
        cur.execute(
            """INSERT INTO price_doctors
               (id, folder_id, name, specialty, crm, rqe, position_order, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (doctor_id, folder_id, doctor_name, doctor_name, "", "", idx_d, now),
        )
        doctor_count += 1

        for idx_p, p in enumerate(doc["procedures"]):
            cur.execute(
                """INSERT INTO price_procedures
                   (id, doctor_id, name, value_cash, value_card_pix, value_bradesco, value_brv, value_prefeitura, position_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()),
                    doctor_id,
                    p["name"],
                    p["value_cash"],
                    p["value_card_pix"],
                    p["value_bradesco"],
                    p["value_brv"],
                    p["value_prefeitura"],
                    idx_p,
                ),
            )
            proc_count += 1

    conn.commit()
    conn.close()
    print(f"OK: {doctor_count} especialidades e {proc_count} procedimentos importados.")


if __name__ == "__main__":
    main()
