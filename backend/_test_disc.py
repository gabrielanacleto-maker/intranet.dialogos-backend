import json
from fastapi.testclient import TestClient
import main
from auth import create_token

client = TestClient(main.app)

# admin token (gabriel, dev/admin)
tok = create_token({"sub": "gabriel", "level": 3})
H = {"Authorization": f"Bearer {tok}"}

# pick a real colaborador for the test link
from database import get_db_context
with get_db_context() as db:
    u = db.execute("SELECT key, name FROM users WHERE desligado=0 AND key NOT IN ('gabriel','tairla','malu') LIMIT 1").fetchone()
    AVA = u["key"]; AVA_NAME = u["name"]
print("AVALIANDO:", AVA, "|", AVA_NAME)

r = client.post("/api/disc/avaliacoes", json={"avaliando_id": AVA}, headers=H)
print("CREATE:", r.status_code, json.dumps(r.json(), ensure_ascii=False))

if r.status_code == 200:
    data = r.json()
    token = data["link"].split("/")[-1]
    link = "http://localhost:8000/disc/avaliacao/" + token
    print("LINK DE TESTE:", link)

    # public info to confirm it's loadable
    info = client.get(f"/api/public/disc/{token}/info")
    print("INFO:", info.status_code, json.dumps(info.json(), ensure_ascii=False))

    # load perguntas and do a full valid submission to confirm flow works
    q = client.get(f"/api/public/disc/{token}/perguntas").json()["perguntas"]
    print("PERGUNTAS:", len(q))
    payload = []
    for qi, pergunta in enumerate(q):
        for i, alt in enumerate(pergunta["alternativas"]):
            pts = {0:4,1:3,2:2,3:1}[i]
            payload.append({"pergunta_id": pergunta["id"], "alternativa_id": alt["id"], "pontuacao": pts})
    sub = client.post(f"/api/public/disc/{token}/respostas", json={"respostas": payload})
    print("SUBMIT:", sub.status_code, json.dumps(sub.json(), ensure_ascii=False))
    det = client.get(f"/api/disc/avaliacoes/{data['id']}", headers=H).json()
    print("RESULT:", det["avaliacao"]["perfil_principal"], det["avaliacao"]["codenome"], "total", det["avaliacao"]["pontuacao_total"])
