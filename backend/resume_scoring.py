"""
Motor de avaliação de currículos e perfil DISC para o módulo de Contratação.

Estratégia plugável: se houver OPENAI_API_KEY no ambiente, pode-se plugar um LLM;
por padrão usa heurística determinística (palavras-chave, requisitos, formação,
senioridade e completude) — sem dependência externa.
"""

import io
import re
import unicodedata


# ── Utilidades ─────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """lowercase + remove acentos, mantendo apenas caracteres simples."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s.lower())


STOPWORDS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "com", "em",
             "para", "por", "que", "no", "na", "nos", "nas", "um", "uma", "ou"}


def _tokens(s: str):
    return [t for t in _norm(s).replace(",", " ").replace(";", " ").split()
            if len(t) > 2 and t not in STOPWORDS]


def _split_items(s: str):
    """Divide um campo em itens por linha, vírgula ou ponto-e-vírgula."""
    if not s:
        return []
    parts = re.split(r"[\n;]+|,(?![0-9])", s)
    return [p.strip() for p in parts if p.strip()]


# ── Extração de texto de currículo ─────────────────────────────────────────────

def extract_resume_text(file_bytes: bytes, filename: str = "") -> str:
    """Extrai texto de PDF (pypdf). Outros formatos retornam vazio."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or file_bytes[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pages.append("")
            return "\n".join(pages)
        except Exception:
            return ""
    return ""


# ── DISC ───────────────────────────────────────────────────────────────────────

# 8 grupos x 4 afirmacoes na ordem [D, I, S, C]
DISC_QUESTIONS = [
    ["Assumo o controle e decido rápido quando algo é urgente.",
     "Comunico com entusiasmo e mobilizo as pessoas ao meu redor.",
     "Mantenho a calma e sigo o ritmo do grupo com paciência.",
     "Analiso todos os detalhes antes de tomar uma decisão."],
    ["Enfrento conflitos de frente em busca de resultados.",
     "Crio conexões facilmente com pessoas desconhecidas.",
     "Prefiro ambientes estáveis e rotinas bem definidas.",
     "Sigo normas e processos com precisão."],
    ["Gosto de desafios grandes e de competir por metas.",
     "Sou otimista mesmo diante de problemas.",
     "Sou um bom ouvinte e apoio meus colegas.",
     "Exijo exatidão e qualidade em tudo que entrego."],
    ["Tomo iniciativas sem precisar que me mandem.",
     "Persuado as pessoas com facilidade.",
     "Trabalho melhor em equipe, de forma cooperativa.",
     "Organizo meu trabalho de forma metódica."],
    ["Falo e ajo com rapidez e firmeza.",
     "Sou expressivo(a) e gosto de ser reconhecido(a).",
     "Evito mudanças bruscas e prefiro previsibilidade.",
     "Reviso meu trabalho várias vezes antes de entregar."],
    ["Assumo riscos calculados para vencer desafios.",
     "Animo o ambiente com humor e energia.",
     "Mantenho a harmonia mesmo sob pressão.",
     "Baseio minhas decisões em fatos e dados."],
    ["Lidero grupos naturalmente quando necessário.",
     "Faço amizades e networking com facilidade.",
     "Sou consistente e confiável nas minhas entregas.",
     "Cumpro regras e prazos à risca."],
    ["Vou direto ao ponto nas conversas.",
     "Gosto de trabalhar com público e apresentar ideias.",
     "Prefiro ouvir antes de dar minha opinião.",
     "Gosto de ter um plano detalhado antes de executar."],
]

DIMENSIONS = ["D", "I", "S", "C"]
DIMS_PT = {"D": "Dominância", "I": "Influência", "S": "Estabilidade", "C": "Conformidade"}


def compute_disc(most: list, least: list) -> dict:
    """
    most/least: listas de índices 0..3 (dimensão escolhida por questão).
    Retorna {'d': pct, 'i': pct, 's': pct, 'c': pct, 'perfil': 'DI', ...}.
    """
    raw = {k: 0.0 for k in DIMENSIONS}
    n_groups = len(DISC_QUESTIONS)
    valid = 0
    for i in range(n_groups):
        m = most[i] if i < len(most) else None
        l = least[i] if i < len(least) else None
        if m is None or l is None or m == l or not (0 <= int(m) <= 3) or not (0 <= int(l) <= 3):
            continue
        raw[DIMENSIONS[int(m)]] += 2
        raw[DIMENSIONS[int(l)]] -= 1
        valid += 1
    # normaliza para escala positiva e depois para 100%
    shifted = {k: max(v, 0) + 1 for k, v in raw.items()}
    total = sum(shifted.values()) or 1
    pct = {k.lower(): round(100 * v / total) for k, v in shifted.items()}
    # corrige arredondamento para somar 100
    diff = 100 - sum(pct.values())
    if diff:
        key_max = max(pct, key=pct.get)
        pct[key_max] += diff
    ordered = sorted(pct.items(), key=lambda kv: kv[1], reverse=True)
    perfil = ("".join(k.upper() for k, _ in ordered[:2]))
    return {
        **pct,
        "valid_answers": valid,
        "perfil": perfil,
        "descricao": DESCRICAO_PERFIL.get(perfil, ""),
        "dimensoes": DIMS_PT,
    }


DESCRICAO_PERFIL = {
    "D": "Perfil dominante: decisivo, competitivo e orientado a resultados.",
    "I": "Perfil influente: comunicativo, otimista e persuasivo.",
    "S": "Perfil estável: paciente, cooperativo e confiável.",
    "C": "Perfil conformista: analítico, preciso e organizado.",
    "DI": "Iniciativa e comunicação: lidera pelo entusiasmo e pela ação rápida.",
    "DC": "Determinação e análise: decisivo, porém baseado em fatos e dados.",
    "ID": "Carisma e iniciativa: mobiliza pessoas e busca resultados visíveis.",
    "IS": "Comunicação e apoio: cria vínculos e mantém um ambiente positivo.",
    "SC": "Consistência e precisão: confiável, metódico e atento aos detalhes.",
    "SD": "Calma firme e ação: estabilidade com coragem pontual para decidir.",
    "CD": "Precisão e força: exige qualidade enquanto conduz à meta.",
    "CI": "Análise e expressão: rigor técnico aliado a boa comunicação.",
}


# ── Score de aderência do candidato à vaga ─────────────────────────────────────

SENIORIDADE_MAP = {
    "jr": ["junior", "júnior", "jr", "estagiario", "estagiária", "trainee", "auxiliar"],
    "pl": ["pleno", "pl", "intermediario", "intermediário"],
    "sr": ["senior", "sênior", "sr", "especialista", "master"],
}


def _senioridade_key(s: str):
    n = _norm(s)
    if any(w in n for w in SENIORIDADE_MAP["sr"]):
        return "sr"
    if any(w in n for w in SENIORIDADE_MAP["pl"]):
        return "pl"
    if any(w in n for w in SENIORIDADE_MAP["jr"]):
        return "jr"
    return None


def score_candidato(vaga: dict, resume_text: str, respostas: str = "") -> dict:
    """
    Calcula aderência 0-100 do candidato à vaga.
    Componentes: palavras_chave (35), requisitos (30), formação (15),
    senioridade (10), perfil/completude (10).
    Pesos não utilizados são redistribuídos para requisitos.
    """
    texto = _norm(resume_text or "")
    resp = _norm(respostas or "")
    corpus = f"{texto} {resp}"

    breakdown = {}
    w_kw, w_req, w_form, w_sen, w_perfil = 35, 30, 15, 10, 10

    keywords = [k.strip() for k in _split_items(vaga.get("palavras_chave", "") or "")]
    if not keywords:
        w_req += w_kw
        w_kw = 0

    # 1) Palavras-chave
    kw_hits = []
    if keywords:
        for k in keywords:
            if _norm(k) and _norm(k) in corpus:
                kw_hits.append(k)
        pts = round(w_kw * len(kw_hits) / len(keywords))
    else:
        pts = 0
        kw_hits = []
    breakdown["palavras_chave"] = {
        "pontos": pts, "max": w_kw,
        "encontradas": kw_hits, "total": len(keywords),
    }

    # 2) Requisitos essenciais
    reqs = _split_items(vaga.get("requisitos", "") or "")
    req_ok = []
    if reqs:
        for r in reqs:
            toks = _tokens(r)
            if not toks:
                continue
            hits = sum(1 for t in toks if t in corpus)
            if hits / len(toks) >= 0.6:
                req_ok.append(r)
        pts = round(w_req * len(req_ok) / len(reqs))
    else:
        pts = 0
    breakdown["requisitos"] = {"pontos": pts, "max": w_req,
                               "atendidos": req_ok, "total": len(reqs)}

    # 3) Formação acadêmica
    form_tokens = _tokens(vaga.get("formacao", "") or "")
    if form_tokens:
        hits = sum(1 for t in form_tokens if t in corpus)
        pts = round(w_form * min(hits / max(len(form_tokens) * 0.6, 1), 1))
    else:
        pts = 0
        w_form = 0
    breakdown["formacao"] = {"pontos": pts, "max": w_form}

    # 4) Senioridade
    alvo = _senioridade_key(vaga.get("senioridade", "") or "")
    if alvo:
        tem = _senioridade_key(resume_text or "") or (
            _senioridade_key(respostas or ""))
        if tem == alvo:
            pts = w_sen
        elif tem and abs(["jr", "pl", "sr"].index(tem) - ["jr", "pl", "sr"].index(alvo)) == 1:
            pts = round(w_sen / 2)
        else:
            pts = 0
    else:
        pts = 0
        w_sen = 0
    breakdown["senioridade"] = {"pontos": pts, "max": w_sen}

    # 5) Completude do currículo / perfil preenchido
    pts_perfil = 0
    if len(texto) > 1200:
        pts_perfil += 6
    elif len(texto) > 400:
        pts_perfil += 4
    elif len(texto) > 0:
        pts_perfil += 2
    if "@" in (resume_text or ""):
        pts_perfil += 2
    if resp:
        pts_perfil += 2
    breakdown["perfil"] = {"pontos": min(pts_perfil, w_perfil), "max": w_perfil}

    total = sum(b["pontos"] for b in breakdown.values())
    total_max = sum(b["max"] for b in breakdown.values()) or 100
    score = round(100 * total / total_max)

    return {"score": score, "breakdown": breakdown}
