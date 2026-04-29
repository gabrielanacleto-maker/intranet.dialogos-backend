import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';

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

  return (
    <div className="login-screen">
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
  );
}