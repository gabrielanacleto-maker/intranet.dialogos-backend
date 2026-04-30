import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { AV_COLORS, LEVEL_LABEL, LEVEL_BADGE_CLASS, CURSOR_OPTIONS, getRoleClass, getTenureLabel, getTenureClass, getRoleGlowClass, getRoleStyle } from '../utils';
import MoodReport from '../components/MoodReport';

export default function ProfilePage() {
  const { user, refreshUsers } = useAuth();
  const toast = useToast();
  const [photo, setPhoto] = useState(null);
  const [cursorStyle, setCursorStyle] = useState(() => localStorage.getItem('dialogos_cursor') || 'normal');
  const [uploading, setUploading] = useState(false);
  const [showPassModal, setShowPassModal] = useState(false);
  const [passForm, setPassForm] = useState({ current: '', newPass: '', confirm: '' });
  const [saving, setSaving] = useState(false);
  const [roleDraft, setRoleDraft] = useState('');
  const [savingRole, setSavingRole] = useState(false);

  useEffect(() => {
    if (user?.photo_url) setPhoto(api.assetUrl(user.photo_url));
  }, [user]);

  useEffect(() => {
    setRoleDraft(user?.role || '');
  }, [user?.role]);

  useEffect(() => {
    const body = document.body;
    CURSOR_OPTIONS.forEach(c => body.classList.remove(`cursor-${c.key}`));
    body.classList.add(`cursor-${cursorStyle}`);
    localStorage.setItem('dialogos_cursor', cursorStyle);
  }, [cursorStyle]);

  async function handlePhotoUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.uploadPhoto(file);
      const url = api.assetUrl(res.url);
      setPhoto(url);
      await refreshUsers();
      toast('Foto atualizada!', 'success');
    } catch (err) { toast(err.message, 'error'); }
    finally { setUploading(false); e.target.value = ''; }
  }

  async function handleChangePass(e) {
    e.preventDefault();
    if (passForm.newPass.length < 6) return toast('Nova senha precisa ter ao menos 6 caracteres.', 'error');
    if (passForm.newPass !== passForm.confirm) return toast('Senhas não coincidem.', 'error');
    setSaving(true);
    try {
      await api.changePassword(passForm.current, passForm.newPass);
      toast('Senha alterada com sucesso!', 'success');
      setShowPassModal(false);
      setPassForm({ current: '', newPass: '', confirm: '' });
    } catch (err) { toast(err.message, 'error'); }
    finally { setSaving(false); }
  }

  async function handleSaveRole() {
    const newRole = roleDraft.trim();
    if (!newRole) return toast('Informe um cargo válido.', 'error');
    if (newRole === user.role) return;
    setSavingRole(true);
    try {
      await api.updateUser(user.key, {
        name: user.name,
        initials: user.initials,
        role: newRole,
        dept: user.dept,
        level: user.level,
        color: user.color,
        access_level: user.access_level,
        is_admin: !!user.is_admin,
        is_admin_user: !!user.is_admin_user,
        is_rh: !!user.is_rh,
        is_ouvidor: !!user.is_ouvidor,
        points: user.points,
        hire_date: user.hire_date || '',
        org_position: user.org_position || 'colaborador',
        is_orcoma: !!user.is_orcoma,
      });
      toast('Cargo atualizado com sucesso!', 'success');
      window.location.reload();
    } catch (err) {
      toast(err.message || 'Erro ao atualizar cargo.', 'error');
    } finally {
      setSavingRole(false);
    }
  }

  if (!user) return null;

  const avatarBg = AV_COLORS[user.color] || '#C9A84C';
  const roleStyle = getRoleStyle(user.role, user.is_rh, user.is_admin);

  return (
    <div>
      <div className="section-title">👤 Meu Perfil</div>

      {/* Hero */}
      <div style={{ background: 'linear-gradient(135deg, #2A2618 0%, #1C1A14 100%)', borderRadius: 'var(--radius)', padding: 32, textAlign: 'center', marginBottom: 20, border: '1px solid rgba(201,168,76,0.2)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 100, height: 100, borderRadius: '50%', border: '3px solid var(--gold)', background: avatarBg, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', boxShadow: '0 0 24px rgba(201,168,76,0.25)' }}>
            {photo
              ? <img src={photo} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt={user.name} onError={() => setPhoto(null)} />
              : <span style={{ fontFamily: 'Playfair Display', fontSize: 36, fontWeight: 700, color: '#fff' }}>{user.initials}</span>}
          </div>
          <label className="change-photo-btn" style={{ cursor: uploading ? 'wait' : 'pointer' }}>
            {uploading ? '⏳ Enviando...' : '📷 Alterar Foto'}
            <input type="file" accept="image/*" hidden onChange={handlePhotoUpload} />
          </label>
          <div>
            <div style={{ fontFamily: 'Playfair Display', fontSize: 22, color: '#E8E0CC', fontWeight: 600, marginBottom: 4 }}>{user.name}</div>
            <div className={`profile-role ${getRoleClass(user.role)}`} style={{ marginBottom: 4, ...roleStyle }}>{user.role}</div>
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginBottom: 14 }}>{user.dept}</div>
            <div style={{ display: 'flex', gap: 6, justifyContent: 'center', flexWrap: 'wrap' }}>
              <span className={`access-badge ${LEVEL_BADGE_CLASS[user.level] || 'badge-dourado'}`}>{LEVEL_LABEL[user.level]}</span>
              {!!user.is_rh && <span className="access-badge badge-rh">🧬 RH</span>}
              {!!user.is_ouvidor && <span className="access-badge badge-ouvidor">👁️ Ouvidor</span>}
              {!!user.is_admin_user && !user.is_admin && <span className="access-badge badge-admin-user">🛡️ Admin User</span>}
              {!!user.is_admin && (
                <span className="access-badge" style={{
                  background: 'linear-gradient(90deg, #cc0000, #ff4444)',
                  color: '#fff',
                  border: '2px solid #ff0000',
                  boxShadow: '0 0 10px rgba(255,0,0,0.4)',
                }}>⚡ Admin System</span>
              )}
              {!!user.is_orcoma && <span className="access-badge badge-orcoma">🔷 Orcoma</span>}
            </div>
            {getTenureLabel(user.hire_date) && (
              <div className={`tenure-badge ${getTenureClass(user.hire_date)}`} style={{ marginTop: 8 }}>
                🗓️ {getTenureLabel(user.hire_date)}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Info grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 20 }}>
        {[
          { label: 'Cargo', value: user.role },
          { label: 'Setor', value: user.dept },
          { label: 'Login', value: `@${user.key}` },
          { label: 'Pontos', value: `⭐ ${user.points}` },
        ].map(item => (
          <div key={item.label} className="surface-card" style={{ padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6 }}>{item.label}</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{item.value}</div>
          </div>
        ))}
      </div>

      {/* Security section */}
      <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 14 }}>🔐 Segurança</div>
        <button className="btn-admin btn-secondary" onClick={() => setShowPassModal(true)}>
          🔑 Alterar minha senha
        </button>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>Sua senha é armazenada com criptografia. Nunca é visível para ninguém.</p>
      </div>

      {/* Role section */}
      <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 6 }}>✏️ Cargo no Sistema</div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          Você pode ajustar livremente a nomenclatura do seu cargo.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="text"
            value={roleDraft}
            onChange={e => setRoleDraft(e.target.value)}
            placeholder="Ex: Admin Server"
            style={{ flex: '1 1 260px', minWidth: 220, padding: '10px 12px', borderRadius: 8, border: '1.5px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}
          />
          <button className="btn-admin btn-primary" onClick={handleSaveRole} disabled={savingRole}>
            {savingRole ? 'Salvando...' : 'Salvar Cargo'}
          </button>
        </div>
      </div>

      {/* Cursor customizer */}
      <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 6 }}>🖱️ Cursor do Mouse</div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>Personalize o efeito visual do cursor enquanto você navega pela intranet.</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
          {CURSOR_OPTIONS.map(opt => (
            <div key={opt.key} className={`cursor-option${cursorStyle === opt.key ? ' selected' : ''}`} onClick={() => setCursorStyle(opt.key)}>
              <span style={{
                display: 'inline-block', width: 18, height: 18, borderRadius: '50%',
                background: opt.color, border: opt.border || '2px solid transparent',
                flexShrink: 0, boxShadow: opt.key !== 'normal' ? `0 0 8px ${opt.color}88` : 'none'
              }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>{opt.label}</span>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
          ✨ A preferência fica salva no seu navegador automaticamente.
        </p>
      </div>

      {/* Relatório de Humor */}
      <MoodReport />

      {/* Change password modal */}
      {showPassModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowPassModal(false)}>
          <div className="modal-card" style={{ maxWidth: 420 }}>
            <div className="modal-header">
              <div className="modal-title">🔑 Alterar Senha</div>
              <button className="modal-close" onClick={() => setShowPassModal(false)}>✕</button>
            </div>
            <form onSubmit={handleChangePass}>
              <div className="admin-form">
                <div className="admin-field">
                  <label>Senha atual</label>
                  <input type="password" value={passForm.current} onChange={e => setPassForm(p => ({ ...p, current: e.target.value }))} placeholder="••••••••" />
                </div>
                <div className="admin-field">
                  <label>Nova senha</label>
                  <input type="password" value={passForm.newPass} onChange={e => setPassForm(p => ({ ...p, newPass: e.target.value }))} placeholder="Mínimo 6 caracteres" />
                </div>
                <div className="admin-field">
                  <label>Confirmar nova senha</label>
                  <input type="password" value={passForm.confirm} onChange={e => setPassForm(p => ({ ...p, confirm: e.target.value }))} placeholder="Repita a nova senha" />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn-admin btn-secondary" onClick={() => setShowPassModal(false)}>Cancelar</button>
                <button type="submit" className="btn-admin btn-primary" disabled={saving}>{saving ? 'Salvando...' : 'Alterar Senha'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}