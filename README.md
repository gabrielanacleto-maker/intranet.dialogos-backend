# 🏥 Intranet — Clínica Diálogos

Projeto full-stack: **FastAPI (backend)** + **React/Vite (frontend)** + **SQLite (banco de dados portátil)**.

---

## 📁 Estrutura

```
dialogos/
├── backend/
│   ├── main.py          ← Todos os endpoints REST
│   ├── database.py      ← Inicialização do SQLite + seed
│   ├── auth.py          ← JWT + hash de senha (pbkdf2)
│   ├── models.py        ← Schemas Pydantic
│   ├── requirements.txt
│   ├── .env.example
│   └── start.sh
│
└── frontend/
    ├── src/
    │   ├── App.jsx            ← Shell principal (layout, roteamento)
    │   ├── main.jsx           ← Ponto de entrada React
    │   ├── index.css          ← Todos os estilos (cursor, brilho, temas)
    │   ├── utils.js           ← Funções utilitárias, cores, embeds
    │   ├── services/api.js    ← Camada de comunicação com a API
    │   ├── context/
    │   │   ├── AuthContext.jsx    ← Login, logout, RBAC
    │   │   └── ToastContext.jsx   ← Notificações
    │   ├── components/
    │   │   └── CursorGlow.jsx     ← Efeito de cursor customizável
    │   └── pages/
    │       ├── LoginPage.jsx
    │       ├── ChangePasswordPage.jsx  ← Tela de primeiro acesso
    │       ├── FeedPage.jsx            ← Feed + embeds + upload de imagem
    │       ├── NovidadesPage.jsx       ← Mural + carrossel + Feed Novidades
    │       ├── DocsPage.jsx            ← Pastas + upload de documentos
    │       ├── AdminPage.jsx           ← Gerenciar usuários + logs
    │       └── ProfilePage.jsx         ← Perfil + cursor + trocar senha
    ├── index.html
    ├── vite.config.js
    ├── package.json
    └── .env.example
```

---

## ▶️ Como rodar no VS Code

### 1. Backend

```bash
cd backend

# Crie o .env
cp .env.example .env

# Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate          # Linux/Mac
# ou: venv\Scripts\activate       # Windows

# Instale as dependências
pip install -r requirements.txt

# Inicie o servidor
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

✅ Backend rodando em: http://localhost:8000
📚 Documentação da API: http://localhost:8000/docs

---

### 2. Frontend (novo terminal)

```bash
cd frontend

# Crie o .env
cp .env.example .env

# Instale as dependências
npm install

# Inicie o servidor de desenvolvimento
npm run dev
```

✅ Frontend rodando em: http://localhost:5173

---

## 🔑 Credenciais Iniciais

| Login | Senha | Nível |
|---|---|---|
| `gabriel` | `dialogos@2025` | 3 — Super Admin (acesso total) |
| `tairla` | `trocar123` | 2 — Admin User (será forçada a trocar no 1º acesso) |
| `malu` | `trocar123` | 1 — Funcionária (será forçada a trocar no 1º acesso) |

---

## 🔐 Hierarquia de Segurança (RBAC)

| Nível | Quem | Pode |
|---|---|---|
| **3** | Admin Server (Gabriel) | Tudo — resetar qualquer usuário |
| **2** | Admin User (Liderança) | Resetar apenas Níveis 0 e 1. **Nunca** pode tocar em Nível 2 ou 3 |
| **1/0** | Funcionários | Sem acesso ao painel admin |

### Lógica de Primeiro Acesso
- `password_changed = False` → sistema redireciona para tela de troca obrigatória
- Após trocar: `password_changed = True` → acesso liberado
- Ao resetar via admin: volta para `False` automaticamente

---

## 🖱️ Cursor Customizável

Disponível em **Meu Perfil → Cursor do Mouse**:
- 9 opções: Normal, Dourado, Vermelho, Azul, Rosa, Branco, Verde, Roxo, Laranja, Ciano
- Salvo automaticamente no `localStorage` do navegador
- Implementado como CSS puro (sem performance overhead)

---

## 📡 Acesso pela Rede Local

Para acessar de outros computadores da clínica:

1. Descubra o IP do servidor: `ipconfig` (Windows) ou `ip addr` (Linux)
2. No frontend `.env`, mude: `VITE_API_URL=http://192.168.X.X:8000`
3. Acesse pelo navegador de qualquer PC na rede: `http://192.168.X.X:5173`

---

## 📦 Banco de Dados (SQLite)

- Arquivo: `backend/dialogos.db`
- Portátil: para migrar de computador, basta copiar este arquivo
- Uploads ficam em: `backend/uploads/`

---

## 🚀 Próximos Passos Sugeridos

- **Ranking** — integrar página de ranking com pontuação real
- **Equipe** — listar colaboradores com cards de perfil
- **Ouvidoria** — página completa com filtragem por status
- **Organograma** — visualização hierárquica da equipe
- **Tabela de Preços** — integrar profissionais/procedimentos ao backend
- **Build de produção**: `npm run build` → servir com Nginx
