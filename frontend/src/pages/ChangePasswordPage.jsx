import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';

export default function ChangePasswordPage() {
  const { user, setMustChangePassword } = useAuth();
  const toast = useToast();
  const [current, setCurrent] = useState('');
  const [newPass, setNewPass] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (newPass.length < 6) return toast('A nova senha precisa ter ao menos 6 caracteres.', 'error');
    if (newPass !== confirm) return toast('As senhas não coincidem.', 'error');
    setLoading(true);
    try {
      await api.changePassword(current, newPass);
      toast('Senha alterada com sucesso! Bem-vindo(a)!', 'success');
      setMustChangePassword(false);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="change-pass-screen">
      <div className="change-pass-card">
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🔐</div>
          <h2 style={{ fontFamily: 'Playfair Display', fontSize: 22, marginBottom: 8 }}>
            Primeiro Acesso
          </h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Olá, <strong>{user?.name?.split(' ')[0]}</strong>! Por segurança, você precisa
            criar uma senha pessoal antes de continuar.
          </p>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Senha temporária (fornecida pelo admin)</label>
            <input type="password" value={current} onChange={e => setCurrent(e.target.value)} placeholder="••••••••" />
          </div>
          <div className="form-group">
            <label>Nova Senha</label>
            <input type="password" value={newPass} onChange={e => setNewPass(e.target.value)} placeholder="Mínimo 6 caracteres" />
          </div>
          <div className="form-group">
            <label>Confirmar Nova Senha</label>
            <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Repita a nova senha" />
          </div>
          <button type="submit" className="btn-login" disabled={loading} style={{ marginTop: 8 }}>
            {loading ? 'Salvando...' : 'Definir Minha Senha e Entrar'}
          </button>
        </form>
        <p style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', marginTop: 16 }}>
          🔒 Sua senha é criptografada e segura. Nem o administrador pode vê-la.
        </p>
      </div>
    </div>
  );
}
