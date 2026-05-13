import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import {
  AV_COLORS, LEVEL_LABEL, LEVEL_BADGE_CLASS, CURSOR_OPTIONS,
  getRoleClass, getTenureLabel, getTenureClass, getRoleStyle
} from '../utils';
import MoodReport from '../components/MoodReport';
import {
  AboutMeSection,
  InfoGrid,
  InternalReviewsSection,
  ProfileHero,
  ProfileRelations,
} from './ColleagueProfilePage';

// ─── Avatar inline ──────────────────────────────────────────
function UserAvatar({ photoUrl, name, size = 48 }) {
  const [broken, setBroken] = useState(false);
  const initials = name?.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase() || '?';
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      border: '2px solid var(--gold)', overflow: 'hidden', flexShrink: 0,
      background: '#2A2618', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {photoUrl && !broken
        ? <img src={photoUrl} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            onError={() => setBroken(true)} />
        : <span style={{ fontSize: size * 0.35, fontWeight: 700, color: 'var(--gold)' }}>{initials}</span>}
    </div>
  );
}

// ─── Card de membro ─────────────────────────────────────────
function MemberCard({ member }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '10px 12px', borderRadius: 8,
      background: 'rgba(201,168,76,0.05)', border: '1px solid rgba(201,168,76,0.12)',
    }}>
      <UserAvatar photoUrl={member.photo_url ? api.assetUrl(member.photo_url) : null} name={member.name} size={40} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{member.name}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{member.role}</div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', opacity: 0.7 }}>{member.dept}</div>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { user, refreshUsers } = useAuth();
  const toast = useToast();

  const [photo, setPhoto] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [cursorStyle, setCursorStyle] = useState(() => localStorage.getItem('dialogos_cursor') || 'normal');
  const [showPassModal, setShowPassModal] = useState(false);
  const [passForm, setPassForm] = useState({ current: '', newPass: '', confirm: '' });
  const [saving, setSaving] = useState(false);
  const [roleDraft, setRoleDraft] = useState(user?.role || '');
  const [savingRole, setSavingRole] = useState(false);

  // Gestor
  const [manager, setManager] = useState(null);
  const [gestores, setGestores] = useState([]);
  const [editingManager, setEditingManager] = useState(false);
  const [selectedManagerKey, setSelectedManagerKey] = useState('');
  const [savingManager, setSavingManager] = useState(false);

  // Equipe
  const [teamData, setTeamData] = useState(null);

  useEffect(() => {
    if (!user) return;
    setRoleDraft(user.role || '');
    if (user.photo_url) setPhoto(api.assetUrl(user.photo_url));
  }, [user]);

  useEffect(() => {
    const body = document.body;
    CURSOR_OPTIONS.forEach(c => body.classList.remove(`cursor-${c.key}`));
    body.classList.add(`cursor-${cursorStyle}`);
    localStorage.setItem('dialogos_cursor', cursorStyle);
  }, [cursorStyle]);

 const loadManagerAndTeam = useCallback(async () => {
  if (!user) return;
  try {
    const [managerRes, teamRes] = await Promise.all([
      api.getUserManager(user.key),
      api.getUserTeam(user.key),
    ]);
    setManager(managerRes.manager || null);
    setTeamData(teamRes);
    setSelectedManagerKey(managerRes.manager?.key || '');
  } catch (err) {
    console.error('Erro ao carregar gestor/equipe:', err);
  }
}, [user]);

  useEffect(() => { loadManagerAndTeam(); }, [loadManagerAndTeam]);

  async function handleOpenEditManager() {
  if (!editingManager && gestores.length === 0) {
    try {
      const list = await api.getGestores();
      setGestores(list);
    } catch (err) {
      toast('Erro ao carregar lista de gestores', 'error');
    }
  }
  setEditingManager(v => !v);
}

async function saveManager() {
  setSavingManager(true);
  try {
    await api.assignManager({
      target_user_key: user.key,
      manager_key: selectedManagerKey || null,
    });
    toast('Gestor atualizado com sucesso!', 'success');
    setEditingManager(false);
    await loadManagerAndTeam();
    await refreshUsers();
  } catch (err) {
    toast(err.message || 'Erro ao salvar gestor', 'error');
  } finally {
    setSavingManager(false);
  }
}

  async function handlePhotoUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.uploadPhoto(file);
      setPhoto(api.assetUrl(res.url));
      await refreshUsers();
      toast('Foto atualizada!', 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
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
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveRole() {
    const newRole = roleDraft.trim();
    if (!newRole) return toast('Informe um cargo válido.', 'error');
    if (newRole === user.role) return;
    setSavingRole(true);
    try {
      await api.updateUser(user.key, {
        name: user.name, initials: user.initials, role: newRole,
        dept: user.dept, level: user.level, color: user.color,
        access_level: user.access_level,
        is_admin: !!user.is_admin, is_admin_user: !!user.is_admin_user,
        is_rh: !!user.is_rh, is_ouvidor: !!user.is_ouvidor,
        points: user.points, hire_date: user.hire_date || '',
        org_position: user.org_position || 'colaborador',
        is_orcoma: !!user.is_orcoma,
      });
      toast('Cargo atualizado com sucesso!', 'success');
      await refreshUsers();
    } catch (err) {
      toast(err.message || 'Erro ao atualizar cargo.', 'error');
    } finally {
      setSavingRole(false);
    }
  }

  if (!user) return null;

  const avatarBg = AV_COLORS[user.color] || '#C9A84C';
  const roleStyle = getRoleStyle(user.role, user.is_rh, user.is_admin);
  const orgPosition = user.org_position || 'colaborador';
  const showManager = orgPosition !== 'gestor';
  const teamLabel = orgPosition === 'colaborador' ? '👥 Sua Equipe' : '👥 Seus Subordinados';

  const inputStyle = {
    width: '100%', padding: 10, marginBottom: 10,
    borderRadius: 8, background: 'var(--bg)',
    color: 'var(--text)', border: '1.5px solid var(--border)',
    fontFamily: 'inherit', fontSize: 14,
  };

  return (
    <div>
      <div className="section-title">👤 Meu Perfil</div>

      <ProfileHero profileUser={user} photo={photo} onPhotoUpload={handlePhotoUpload} uploading={uploading} isOwnProfile />
      <InfoGrid profileUser={user} />
      <ProfileRelations
        manager={manager}
        teamData={teamData}
        profileUser={user}
        canEditManager={user.is_admin || user.is_admin_user}
        onEditManager={handleOpenEditManager}
        editingManager={editingManager}
        gestores={gestores}
        selectedManagerKey={selectedManagerKey}
        setSelectedManagerKey={setSelectedManagerKey}
        saveManager={saveManager}
        savingManager={savingManager}
      />
      <AboutMeSection profileUser={user} canEdit />
      <InternalReviewsSection loggedUser={user} profileUser={user} />

      {/* Segurança */}
      <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 14 }}>🔐 Segurança</div>
        <button className="btn-admin btn-secondary" onClick={() => setShowPassModal(true)}>
          🔑 Alterar minha senha
        </button>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>Sua senha é armazenada com criptografia. Nunca é visível para ninguém.</p>
      </div>

      {/* Cargo */}
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

      {/* Cursor */}
      <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 6 }}>🖱️ Cursor do Mouse</div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>Personalize o efeito visual do cursor enquanto você navega pela intranet.</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 8 }}>
          {CURSOR_OPTIONS.map(opt => (
            <div key={opt.key} className={`cursor-option${cursorStyle === opt.key ? ' selected' : ''}`} onClick={() => setCursorStyle(opt.key)}>
              <span style={{ display: 'inline-block', width: 18, height: 18, borderRadius: '50%', background: opt.color, border: opt.border || '2px solid transparent', flexShrink: 0, boxShadow: opt.key !== 'normal' ? `0 0 8px ${opt.color}88` : 'none' }} />
              <span style={{ fontSize: 13, fontWeight: 500 }}>{opt.label}</span>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 10 }}>
          ✨ A preferência fica salva no seu navegador automaticamente.
        </p>
      </div>

      <MoodReport />

      {/* Modal senha */}
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
