import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import Loading from './Loading';
import { getActiveTheme, FloatingHearts, ThemeDecorations } from './TemasComemorativos';

export default function LoginPage() {
  const { login } = useAuth();
  const toast = useToast();
  const [key, setKey] = useState('');
  const [pass, setPass] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleLogin(e) {
    e.preventDefault();
    if (!key.trim() || !pass.trim()) return toast('Preencha usuário e senha.', 'error');
    setLoading(true);
    try {
      await login(key.trim().toLowerCase(), pass);
    } catch (err) {
      toast(err.message || 'Erro ao entrar', 'error');
    } finally {
      setLoading(false);
    }
  }

  const theme = getActiveTheme();

  if (loading) return <Loading message="Entrando..." />;

  return (
    <>
      {theme && <ThemeDecorations density={20} />}
      <FloatingHearts count={10} />
      <style>{`
        @keyframes spinSlow {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes floatY {
          0%, 100% { transform: translateY(0px); }
          50%       { transform: translateY(-20px); }
        }
        @keyframes glowPulse {
          0%, 100% { filter: drop-shadow(0 0 40px rgba(212,168,67,0.6), 0 0 80px rgba(212,168,67,0.2), 0 0 120px rgba(212,168,67,0.05)); }
          50%       { filter: drop-shadow(0 0 60px rgba(212,168,67,0.9), 0 0 120px rgba(212,168,67,0.35), 0 0 180px rgba(212,168,67,0.1)); }
        }
        @keyframes twinkle1 {
          0%, 100% { opacity: 0.15; }
          25%      { opacity: 0.4; }
          50%      { opacity: 0.8; }
          75%      { opacity: 0.3; }
        }
        @keyframes twinkle2 {
          0%, 100% { opacity: 0.25; }
          33%      { opacity: 0.7; }
          66%      { opacity: 0.1; }
        }
        @keyframes twinkle3 {
          0%, 100% { opacity: 0.1; }
          50%      { opacity: 0.5; }
        }
        .login-screen::before {
          content: '';
          position: absolute;
          inset: 0;
          background-image:
            radial-gradient(2px 2px at 3% 12%, rgba(212,168,67,0.6) 0%, transparent 100%),
            radial-gradient(2px 2px at 8% 45%, rgba(212,168,67,0.4) 0%, transparent 100%),
            radial-gradient(1px 1px at 15% 78%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(2px 2px at 22% 8%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1px 1px at 28% 55%, rgba(212,168,67,0.6) 0%, transparent 100%),
            radial-gradient(3px 3px at 32% 90%, rgba(212,168,67,0.25) 0%, transparent 100%),
            radial-gradient(1px 1px at 38% 35%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(2px 2px at 42% 70%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1px 1px at 48% 15%, rgba(212,168,67,0.45) 0%, transparent 100%),
            radial-gradient(2px 2px at 55% 60%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1px 1px at 62% 25%, rgba(212,168,67,0.55) 0%, transparent 100%),
            radial-gradient(3px 3px at 68% 85%, rgba(212,168,67,0.2) 0%, transparent 100%),
            radial-gradient(1px 1px at 73% 40%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(2px 2px at 78% 10%, rgba(212,168,67,0.4) 0%, transparent 100%),
            radial-gradient(1px 1px at 85% 65%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(2px 2px at 92% 50%, rgba(212,168,67,0.45) 0%, transparent 100%),
            radial-gradient(1px 1px at 95% 20%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(2px 2px at 5% 92%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(1px 1px at 18% 65%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(2px 2px at 58% 92%, rgba(212,168,67,0.4) 0%, transparent 100%);
          pointer-events: none;
          animation: twinkle1 6s ease-in-out infinite;
        }
        .login-stars-layer {
          position: absolute;
          inset: 0;
          background-image:
            radial-gradient(1.5px 1.5px at 5% 25%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(1.5px 1.5px at 12% 60%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1px 1px at 25% 15%, rgba(212,168,67,0.45) 0%, transparent 100%),
            radial-gradient(1.5px 1.5px at 35% 80%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1px 1px at 45% 40%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(2px 2px at 52% 10%, rgba(212,168,67,0.25) 0%, transparent 100%),
            radial-gradient(1px 1px at 60% 75%, rgba(212,168,67,0.4) 0%, transparent 100%),
            radial-gradient(1.5px 1.5px at 72% 50%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1px 1px at 82% 30%, rgba(212,168,67,0.5) 0%, transparent 100%),
            radial-gradient(1.5px 1.5px at 90% 85%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1px 1px at 10% 88%, rgba(212,168,67,0.4) 0%, transparent 100%),
            radial-gradient(1px 1px at 30% 5%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1.5px 1.5px at 48% 95%, rgba(212,168,67,0.45) 0%, transparent 100%),
            radial-gradient(1px 1px at 65% 15%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1.5px 1.5px at 88% 55%, rgba(212,168,67,0.4) 0%, transparent 100%);
          pointer-events: none;
          animation: twinkle2 8s ease-in-out infinite;
        }
        .login-stars-layer-2 {
          position: absolute;
          inset: 0;
          background-image:
            radial-gradient(1px 1px at 2% 50%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1px 1px at 16% 20%, rgba(212,168,67,0.25) 0%, transparent 100%),
            radial-gradient(1px 1px at 40% 5%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1px 1px at 55% 45%, rgba(212,168,67,0.35) 0%, transparent 100%),
            radial-gradient(1px 1px at 70% 95%, rgba(212,168,67,0.25) 0%, transparent 100%),
            radial-gradient(1px 1px at 85% 75%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1px 1px at 95% 35%, rgba(212,168,67,0.25) 0%, transparent 100%),
            radial-gradient(1px 1px at 75% 5%, rgba(212,168,67,0.3) 0%, transparent 100%),
            radial-gradient(1px 1px at 40% 95%, rgba(212,168,67,0.25) 0%, transparent 100%),
            radial-gradient(1px 1px at 60% 35%, rgba(212,168,67,0.3) 0%, transparent 100%);
          pointer-events: none;
          animation: twinkle3 10s ease-in-out infinite;
        }
        .login-screen::after {
          content: '';
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 1px;
          background: linear-gradient(90deg, transparent 0%, rgba(212,168,67,0.3) 50%, transparent 100%);
          animation: goldShimmer 4s ease-in-out infinite;
        }
        .login-symbol-wrapper {
          position: absolute;
          right: 3%;
          top: 23%;
          transform: translateY(-50%);
          animation: floatY 6s ease-in-out infinite;
          pointer-events: none;
        }
        .login-symbol-img {
          width: clamp(260px, 36vw, 480px);
          height: auto;
          animation:
            spinSlow   18s linear infinite,
            glowPulse   4s ease-in-out infinite;
          display: block;
          opacity: 0.85;
        }
        .login-card {
          position: relative;
          overflow: hidden;
        }
        .login-card::before {
          content: '';
          position: absolute;
          top: -50%;
          left: -50%;
          width: 200%;
          height: 200%;
          background: conic-gradient(from 0deg at 50% 50%, transparent 0%, rgba(212,168,67,0.03) 25%, transparent 50%, rgba(212,168,67,0.03) 75%, transparent 100%);
          animation: spinSlow 20s linear infinite;
          pointer-events: none;
        }
        .login-card .form-group input {
          background: rgba(255,255,255,0.03);
          border-color: rgba(255,255,255,0.06);
          color: #e8e0cc;
          transition: border-color 0.3s, box-shadow 0.3s, background 0.3s;
        }
        .login-card .form-group input::placeholder {
          color: rgba(232,224,204,0.2);
        }
        .login-card .form-group input:focus {
          background: rgba(255,255,255,0.05);
          border-color: var(--gold);
          box-shadow: 0 0 0 3px rgba(212,168,67,0.12), 0 0 30px rgba(212,168,67,0.06);
        }
        .login-card .logo-text .l2 {
          background: linear-gradient(135deg, #f7edcc 0%, #d4a843 50%, #9b6f10 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }
        @media (max-width: 768px) {
          .login-symbol-wrapper { display: none; }
          .login-screen::before { display: none; }
        }
      `}</style>

      <div className="login-screen">
        <div className="login-stars-layer" />
        <div className="login-stars-layer-2" />
        {/* Rotating golden symbol */}
        <div className="login-symbol-wrapper">
          <img
            src="/simbolo-dialogos.png"
            alt=""
            className="login-symbol-img"
          />
        </div>

        <div className="login-card">
          <div className="login-logo">
            <div className="logo-icon">
              <img
                src="/logo-clinica-fivecon.ico"
                alt="Logo Clínica Diálogos"
                style={{ width: 40, height: 40, objectFit: 'contain' }}
              />
            </div>
            <div className="logo-text">
              <span className="l1">Clínica</span>
              <span className="l2">Diálogos</span>
            </div>
          </div>
          <h2>Bem-vindo à Intranet</h2>
          <p>Entre com seu usuário e senha</p>
          <form onSubmit={handleLogin}>
            <div className="form-group">
              <label>Usuário</label>
              <input
                type="text" value={key} onChange={e => setKey(e.target.value)}
                placeholder="Digite seu usuário" autoComplete="username"
              />
            </div>
            <div className="form-group">
              <label>Senha</label>
              <input
                type="password" value={pass} onChange={e => setPass(e.target.value)}
                placeholder="••••••••" autoComplete="current-password"
              />
            </div>
            <button type="submit" className="btn-login" disabled={loading}>
              {loading ? 'Entrando...' : 'Entrar na Intranet'}
            </button>
          </form>
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Esqueceu a senha?{' '}
              <span style={{ color: 'var(--gold)', cursor: 'default' }}>
                Contate o administrador do sistema.
              </span>
            </span>
          </div>
        </div>
      </div>
    </>
  );
}
