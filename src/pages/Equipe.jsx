import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { AV_COLORS, LEVEL_BADGE_CLASS, LEVEL_LABEL, getTenureLabel, getTenureClass, getRoleGlowClass } from '../utils';

function UserAvatar({ u, size = 52 }) {
  const photoUrl = u.photo_url ? api.assetUrl(u.photo_url) : null;
  const bg = AV_COLORS[u.color] || '#C9A84C';
  const tenureClass = getTenureClass(u.hire_date);
  return (
    <div className={`team-avatar-wrap ${tenureClass}`} style={{ width: size, height: size, display: 'inline-block', position: 'relative' }}>
      <div className="team-avatar" style={{ width: size, height: size, background: photoUrl ? 'transparent' : bg }}>
        {photoUrl
          ? <img src={photoUrl} alt={u.name} onError={e => e.target.style.display = 'none'} />
          : <span style={{ fontSize: size * 0.35, color: '#fff', fontWeight: 700 }}>{u.initials}</span>}
      </div>
    </div>
  );
}

function UserBadges({ u }) {
  return (
    <div className="badges-row" style={{ justifyContent: 'center', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
      <span className={`access-badge ${LEVEL_BADGE_CLASS[u.level] || 'badge-dourado'}`}>{LEVEL_LABEL[u.level] || u.level}</span>
      {u.is_rh ? <span className="access-badge badge-rh">🧬 RH</span> : null}
      {u.is_ouvidor ? <span className="access-badge badge-ouvidor">👁️ Ouvidor</span> : null}
      {u.is_admin ? <span className="access-badge badge-super-admin">⚡ Admin System</span> : null}
      {u.is_admin_user && !u.is_admin ? <span className="access-badge badge-admin-user">🛡️ Admin User</span> : null}
      {u.is_orcoma ? <span className="access-badge badge-orcoma">🔷 Orcoma</span> : null}
    </div>
  );
}

function OrgCard({ u, tier }) {
  const glowClass = getRoleGlowClass(u.role, u.dept);
  const tenureLabel = getTenureLabel(u.hire_date);
  const tenureClass = getTenureClass(u.hire_date);
  return (
    <div className={`org-card tier-${tier}`}>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
        <UserAvatar u={u} size={56} />
      </div>
      <div className="org-card-name">{u.name}</div>
      <div className={`org-card-role ${glowClass}`}>{u.role}</div>
      {u.dept && <div className="org-card-dept">{u.dept}</div>}
      {tenureLabel && (
        <div className={`tenure-badge ${tenureClass}`} style={{ marginTop: 6 }}>{tenureLabel}</div>
      )}
      <UserBadges u={u} />
    </div>
  );
}

function OrgTierSection({ label, tier, users, editMode, allUsers, localMap, setLocalMap, setDragItem, dragItem }) {
  return (
    <div
      className={`org-tier ${editMode ? 'droppable' : ''}`}
      onDragOver={e => editMode && e.preventDefault()}
      onDrop={() => {
        if (!dragItem || !editMode) return;
        setLocalMap(prev => ({ ...prev, [dragItem.key]: { ...(prev[dragItem.key] || {}), org_tier: tier, parent_key: '' } }));
        setDragItem(null);
      }}
    >
      <div className="org-tier-label">{label}</div>
      <div className="org-tier-cards">
        {users.map(u => (
          <div
            key={u.key}
            draggable={editMode}
            onDragStart={() => editMode && setDragItem(u)}
            className={`org-card-wrap ${editMode ? 'draggable' : ''}`}
          >
            <OrgCard u={u} tier={tier} />
          </div>
        ))}
        {users.length === 0 && (
          <div className="org-empty-slot">{editMode ? 'Arraste colaboradores aqui' : 'Nenhum neste nível'}</div>
        )}
      </div>
    </div>
  );
}

function UserFormModal({ title, initial, onClose, onSave, isNew }) {
  const [form, setForm] = useState({
    key: '', name: '', initials: '', role: '', dept: '',
    level: 'dourado', color: 'av-gold', access_level: 0,
    is_admin: false, is_admin_user: false, is_rh: false, is_ouvidor: false,
    points: 100, password: '',
    hire_date: '', org_position: 'colaborador', is_orcoma: false,
    ...(initial || {}),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSave() {
    if (!form.name.trim()) return setError('Nome é obrigatório');
    if (isNew && !form.key.trim()) return setError('Login é obrigatório');
    if (isNew && !form.password.trim()) return setError('Senha é obrigatória');
    setSaving(true);
    try { await onSave(form); } catch (e) { setError(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 580, maxHeight: '92vh', overflowY: 'auto' }}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          {error && <div style={{ background: '#ff4444', color: '#fff', padding: '8px 12px', borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{error}</div>}
          <div className="admin-form-row">
            {isNew && <div className="form-group"><label>Login (único)</label><input value={form.key} onChange={e => set('key', e.target.value)} placeholder="ex: joao.silva" /></div>}
            <div className="form-group"><label>Nome Completo</label><input value={form.name} onChange={e => set('name', e.target.value)} /></div>
          </div>
          <div className="admin-form-row">
            <div className="form-group"><label>Iniciais</label><input value={form.initials} onChange={e => set('initials', e.target.value)} maxLength={3} /></div>
            <div className="form-group"><label>Cargo</label><input value={form.role} onChange={e => set('role', e.target.value)} /></div>
          </div>
          <div className="admin-form-row">
            <div className="form-group"><label>Setor / Departamento</label><input value={form.dept} onChange={e => set('dept', e.target.value)} /></div>
            <div className="form-group"><label>Data de Admissão</label><input type="date" value={form.hire_date || ''} onChange={e => set('hire_date', e.target.value)} /></div>
          </div>
          <div className="admin-form-row">
            <div className="form-group">
              <label>Nível de Acesso</label>
              <select value={form.access_level} onChange={e => set('access_level', Number(e.target.value))}>
                <option value={0}>0 — Colaborador</option>
                <option value={1}>1 — Colaborador+</option>
                <option value={2}>2 — Admin User</option>
                <option value={3}>3 — Admin System</option>
              </select>
            </div>
            <div className="form-group">
              <label>Posição no Organograma</label>
              <select value={form.org_position} onChange={e => set('org_position', e.target.value)}>
                <option value="colaborador">Colaborador</option>
                <option value="setor">Setor</option>
                <option value="lideranca">Liderança</option>
                <option value="diretoria">Diretoria</option>
              </select>
            </div>
          </div>
          <div className="admin-form-row">
            <div className="form-group">
              <label>Nível de Conquista</label>
              <select value={form.level} onChange={e => set('level', e.target.value)}>
                <option value="dourado">🟡 Dourado</option>
                <option value="platina">⬜ Platina</option>
                <option value="diamante">💎 Diamante</option>
              </select>
            </div>
            <div className="form-group">
              <label>Empresa</label>
              <select value={form.is_orcoma ? 'orcoma' : 'dialogos'} onChange={e => set('is_orcoma', e.target.value === 'orcoma')}>
                <option value="dialogos">🏥 Clínica Diálogos</option>
                <option value="orcoma">🔷 Orcoma</option>
              </select>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 16, padding: '12px 0', borderTop: '1px solid var(--border)' }}>
            {[['is_rh', '🧬 RH'], ['is_ouvidor', '👁️ Ouvidor'], ['is_admin_user', '🛡️ Admin User'], ['is_admin', '⚡ Admin System']].map(([k, lbl]) => (
              <label key={k} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 13 }}>
                <input type="checkbox" checked={!!form[k]} onChange={e => set(k, e.target.checked)} />
                {lbl}
              </label>
            ))}
          </div>
          {isNew && <div className="form-group"><label>Senha Inicial</label><input type="password" value={form.password} onChange={e => set('password', e.target.value)} /></div>}
        </div>
        <div className="modal-footer">
          <button className="btn-admin btn-secondary" onClick={onClose}>Cancelar</button>
          <button className="btn-admin btn-primary" onClick={handleSave} disabled={saving}>{saving ? 'Salvando...' : '✔ Salvar'}</button>
        </div>
      </div>
    </div>
  );
}

export default function Equipe() {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [orgMap, setOrgMap] = useState({});
  const [tab, setTab] = useState('organograma');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [orgEditMode, setOrgEditMode] = useState(false);
  const [localMap, setLocalMap] = useState({});
  const [dragItem, setDragItem] = useState(null);
  const [savingOrg, setSavingOrg] = useState(false);

  const canManage = user.access_level >= 2;

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [usersData, orgEntries] = await Promise.all([
        api.getUsers(),
        api.getOrganogram().catch(() => []),
      ]);
      setUsers(usersData);
      const map = {};
      orgEntries.forEach(e => { map[e.user_key] = e; });
      setOrgMap(map);
      setLocalMap(map);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  async function saveOrganogram() {
    setSavingOrg(true);
    try {
      const entries = Object.entries(localMap).map(([user_key, e]) => ({
        user_key, parent_key: e.parent_key || '', position_order: e.position_order || 0, org_tier: e.org_tier || 'colaborador'
      }));
      await api.saveOrganogram(entries);
      setOrgMap({ ...localMap });
      setOrgEditMode(false);
    } catch (e) { alert('Erro ao salvar: ' + e.message); }
    finally { setSavingOrg(false); }
  }

  const filteredUsers = users.filter(u =>
    [u.name, u.role, u.dept].join(' ').toLowerCase().includes(search.toLowerCase())
  );
  const clinicaUsers = filteredUsers.filter(u => !u.is_orcoma);
  const orcomaUsers = filteredUsers.filter(u => u.is_orcoma);

  // Org tiers
  const getOrgUsers = (tier) => users.filter(u => (localMap[u.key]?.org_tier || u.org_position || 'colaborador') === tier);
  const getOrgSectors = () => {
    const sectors = {};
    users.forEach(u => {
      const tier = localMap[u.key]?.org_tier || u.org_position || 'colaborador';
      if (tier === 'setor' || tier === 'colaborador') {
        const sKey = localMap[u.key]?.parent_key || u.dept || 'Geral';
        if (!sectors[sKey]) sectors[sKey] = [];
        sectors[sKey].push(u);
      }
    });
    return sectors;
  };

  if (loading) return (
    <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
      <div style={{ fontSize: 40 }}>👥</div>
      <p style={{ marginTop: 12 }}>Carregando equipe...</p>
    </div>
  );

  return (
    <div style={{ padding: '20px 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>👥 Gerenciar Equipe</h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>{users.length} colaboradores cadastrados</p>
        </div>
        {canManage && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn-admin btn-primary" onClick={() => setShowAddModal(true)}>+ Adicionar Colaborador</button>
            {tab === 'organograma' && !orgEditMode && (
              <button className="btn-admin btn-secondary" onClick={() => { setLocalMap({ ...orgMap }); setOrgEditMode(true); }}>✏️ Editar Organograma</button>
            )}
            {tab === 'organograma' && orgEditMode && (
              <>
                <button className="btn-admin btn-primary" onClick={saveOrganogram} disabled={savingOrg}>{savingOrg ? 'Salvando...' : '✔ Salvar'}</button>
                <button className="btn-admin btn-secondary" onClick={() => { setLocalMap({ ...orgMap }); setOrgEditMode(false); }}>✕ Cancelar</button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border)', marginBottom: 16 }}>
        {[['organograma', '🏢 Organograma'], ['colaboradores', '👤 Colaboradores']].map(([k, lbl]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: '8px 18px', border: 'none', background: 'none', cursor: 'pointer',
            color: tab === k ? 'var(--gold)' : 'var(--text-muted)',
            borderBottom: tab === k ? '2px solid var(--gold)' : '2px solid transparent',
            fontWeight: tab === k ? 600 : 400, fontSize: 14, fontFamily: 'inherit',
          }}>{lbl}</button>
        ))}
      </div>

      {/* Search */}
      <input
        style={{ width: '100%', padding: '10px 14px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 14, marginBottom: 16, fontFamily: 'inherit' }}
        placeholder="🔍 Buscar colaborador, cargo ou setor..."
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      {/* Organograma Tab */}
      {tab === 'organograma' && (
        <div>
          {orgEditMode && (
            <div style={{ background: 'rgba(212,168,67,0.1)', border: '1px solid rgba(212,168,67,0.3)', borderRadius: 10, padding: '10px 16px', marginBottom: 16, fontSize: 13, color: 'var(--gold)' }}>
              ✏️ Modo de edição ativo — arraste os cards entre os níveis. Lembre-se de salvar!
            </div>
          )}

          {/* Diretoria */}
          <OrgTierSection label="👑 Diretoria" tier="diretoria" users={getOrgUsers('diretoria')} editMode={orgEditMode} allUsers={users} localMap={localMap} setLocalMap={setLocalMap} setDragItem={setDragItem} dragItem={dragItem} />
          <div style={{ display: 'flex', justifyContent: 'center' }}><div style={{ width: 2, height: 32, background: 'var(--border)' }} /></div>

          {/* Liderança */}
          <OrgTierSection label="⭐ Liderança" tier="lideranca" users={getOrgUsers('lideranca')} editMode={orgEditMode} allUsers={users} localMap={localMap} setLocalMap={setLocalMap} setDragItem={setDragItem} dragItem={dragItem} />
          <div style={{ display: 'flex', justifyContent: 'center' }}><div style={{ width: 2, height: 32, background: 'var(--border)' }} /></div>

          {/* Setores */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 20, boxShadow: 'var(--surface-glow)' }}>
            <div style={{ fontSize: 13, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--text-muted)', marginBottom: 16 }}>🏢 Setores & Colaboradores</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
              {Object.entries(getOrgSectors()).map(([sKey, sUsers]) => (
                <div
                  key={sKey}
                  style={{ flex: '1 1 220px', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, minWidth: 200 }}
                  className={orgEditMode ? 'droppable' : ''}
                  onDragOver={e => orgEditMode && e.preventDefault()}
                  onDrop={() => {
                    if (!dragItem || !orgEditMode) return;
                    setLocalMap(prev => ({ ...prev, [dragItem.key]: { ...(prev[dragItem.key] || {}), org_tier: 'colaborador', parent_key: sKey } }));
                    setDragItem(null);
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8, color: 'var(--gold)', marginBottom: 12 }}>{sKey}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {sUsers.map(u => (
                      <div
                        key={u.key}
                        draggable={orgEditMode}
                        onDragStart={() => orgEditMode && setDragItem(u)}
                        style={{ cursor: orgEditMode ? 'grab' : 'default' }}
                      >
                        <OrgCard u={u} tier="colaborador" />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {/* New sector drop zone */}
              {orgEditMode && (
                <div
                  style={{ flex: '1 1 200px', minWidth: 200, border: '2px dashed var(--border)', borderRadius: 10, padding: 14, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}
                  onDragOver={e => e.preventDefault()}
                  onDrop={e => {
                    e.preventDefault();
                    if (!dragItem) return;
                    const name = prompt('Nome do novo setor:');
                    if (name) {
                      setLocalMap(prev => ({ ...prev, [dragItem.key]: { ...(prev[dragItem.key] || {}), org_tier: 'colaborador', parent_key: name } }));
                      setDragItem(null);
                    }
                  }}
                >
                  + Novo Setor
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Colaboradores Tab */}
      {tab === 'colaboradores' && (
        <div>
          {orcomaUsers.length > 0 && (
            <div style={{ marginBottom: 28 }}>
              <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--text-muted)', marginBottom: 12 }}>🔷 Funcionários Orcoma — {orcomaUsers.length}</div>
              <div className="team-grid">
                {orcomaUsers.map(u => (
                  <TeamCard key={u.key} u={u} canManage={canManage} onEdit={() => setEditingUser(u)} />
                ))}
              </div>
            </div>
          )}
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--text-muted)', marginBottom: 12 }}>🏥 Clínica Diálogos — {clinicaUsers.length}</div>
          <div className="team-grid">
            {clinicaUsers.map(u => (
              <TeamCard key={u.key} u={u} canManage={canManage} onEdit={() => setEditingUser(u)} />
            ))}
          </div>
        </div>
      )}

      {showAddModal && (
        <UserFormModal title="Adicionar Colaborador" onClose={() => setShowAddModal(false)} isNew
          onSave={async data => { await api.createUser(data); setShowAddModal(false); loadData(); }} />
      )}
      {editingUser && (
        <UserFormModal title="Editar Colaborador" initial={editingUser} onClose={() => setEditingUser(null)}
          onSave={async data => { await api.updateUser(editingUser.key, data); setEditingUser(null); loadData(); }} />
      )}
    </div>
  );
}

function TeamCard({ u, canManage, onEdit }) {
  const glowClass = getRoleGlowClass(u.role, u.dept);
  const tenureLabel = getTenureLabel(u.hire_date);
  const tenureClass = getTenureClass(u.hire_date);
  return (
    <div className="team-card">
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
        <UserAvatar u={u} size={72} />
      </div>
      <div className="team-name">{u.name}</div>
      <div className={`team-role ${glowClass}`}>{u.role}</div>
      {u.dept && <div className="team-dept">{u.dept}</div>}
      {tenureLabel && <div className={`tenure-badge ${tenureClass}`} style={{ marginTop: 6 }}>{tenureLabel}</div>}
      <UserBadges u={u} />
      {canManage && (
        <button className="btn-admin btn-secondary" style={{ marginTop: 10, padding: '4px 10px', fontSize: 11 }} onClick={onEdit}>✏️ Editar</button>
      )}
    </div>
  );
}
