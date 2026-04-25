import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { AV_COLORS, LEVEL_LABEL, LEVEL_BADGE_CLASS, timeAgo } from '../utils';

const TABS = ['Usuários', 'Logs de Segurança'];

export default function AdminPage() {
  const { user, isLevel2, isLevel3, refreshUsers } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState('Usuários');
  const [users, setUsers] = useState([]);
  const [logs, setLogs] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [showResetModal, setShowResetModal] = useState(null);
  const [resetPass, setResetPass] = useState('');
  const [form, setForm] = useState(defaultForm());
  const [saving, setSaving] = useState(false);

  function defaultForm() {
    return { key: '', name: '', initials: '', role: '', dept: '', level: 'dourado', color: 'av-gold', access_level: 0, is_admin: false, is_admin_user: false, is_rh: false, is_ouvidor: false, points: 100, password: '', hire_date: '', org_position: 'colaborador', is_orcoma: false };
  }

  useEffect(() => { loadUsers(); }, []);
  useEffect(() => { if (tab === 'Logs de Segurança') loadLogs(); }, [tab]);

  async function loadUsers() {
    try { setUsers(await api.getUsers()); } catch (err) { toast(err.message, 'error'); }
  }
  async function loadLogs() {
    try { setLogs(await api.getLogs()); } catch (err) { toast(err.message, 'error'); }
  }

  function canManage(target) {
    if (!target) return false;
    if (isLevel3) return target.key !== user.key; // Level 3 pode tudo exceto a si mesmo na exclusão
    if (isLevel2) return target.access_level < 2; // Level 2 só gerencia level 0/1
    return false;
  }

  async function saveUser() {
    if (!form.name.trim()) return toast('Nome obrigatório.', 'error');
    if (!editingUser && !form.password.trim()) return toast('Senha obrigatória para novo usuário.', 'error');
    if (!editingUser && !form.key.trim()) return toast('Login (chave) obrigatório.', 'error');
    setSaving(true);
    try {
      if (editingUser) {
        await api.updateUser(editingUser.key, form);
        toast('Usuário atualizado!', 'success');
      } else {
        await api.createUser(form);
        toast('Usuário criado! Ele deverá trocar a senha no primeiro acesso.', 'success');
      }
      setShowModal(false);
      setEditingUser(null);
      await loadUsers();
      await refreshUsers();
    } catch (err) { toast(err.message, 'error'); }
    finally { setSaving(false); }
  }

  async function deleteUser(key) {
    if (!confirm('Remover este colaborador permanentemente?')) return;
    try {
      await api.deleteUser(key);
      toast('Colaborador removido.', 'success');
      loadUsers(); refreshUsers();
    } catch (err) { toast(err.message, 'error'); }
  }

  async function doReset() {
    if (!resetPass.trim() || resetPass.length < 4) return toast('Senha temporária muito curta.', 'error');
    try {
      await api.resetPassword(showResetModal.key, resetPass);
      toast(`Senha de ${showResetModal.name} resetada. Ele deverá trocar no próximo acesso.`, 'success');
      setShowResetModal(null); setResetPass('');
      loadLogs();
    } catch (err) { toast(err.message, 'error'); }
  }

  function openEdit(u) {
    setEditingUser(u);
    setForm({
      key: u.key, name: u.name, initials: u.initials, role: u.role,
      dept: u.dept, level: u.level, color: u.color,
      access_level: u.access_level,
      is_admin: !!u.is_admin, is_admin_user: !!u.is_admin_user,
      is_rh: !!u.is_rh, is_ouvidor: !!u.is_ouvidor,
      points: u.points, password: '',
      hire_date: u.hire_date || '', org_position: u.org_position || 'colaborador',
      is_orcoma: !!u.is_orcoma,
    });
    setShowModal(true);
  }

  const f = form;
  const setF = (key, val) => setForm(x => ({ ...x, [key]: val }));

  return (
    <div>
      <div className="section-title">⚙️ Configurações & Admin</div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: 'var(--bg)', borderRadius: 'var(--radius-sm)', padding: 4, border: '1px solid var(--border)', width: 'fit-content' }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ padding: '7px 16px', border: 'none', borderRadius: 6, cursor: 'pointer', fontFamily: 'inherit', fontSize: 13, fontWeight: 600, background: tab === t ? 'var(--surface)' : 'transparent', color: tab === t ? 'var(--gold)' : 'var(--text-muted)', boxShadow: tab === t ? '0 1px 4px rgba(0,0,0,0.08)' : 'none', transition: 'all 0.2s' }}>
            {t}
          </button>
        ))}
      </div>

      {/* ── USERS TAB ── */}
      {tab === 'Usuários' && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {isLevel3 ? 'Acesso total — Nível 3 (Admin Server)' : 'Acesso parcial — Nível 2 (Admin User)'}
            </p>
            <button className="btn-admin btn-primary" onClick={() => { setEditingUser(null); setForm(defaultForm()); setShowModal(true); }}>
              + Adicionar Colaborador
            </button>
          </div>

          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--surface-glow)' }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Colaborador</th>
                  <th>Cargo</th>
                  <th>Nível</th>
                  <th>Pontos</th>
                  <th>Senha</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => {
                  const manageable = canManage(u);
                  const avatarBg = AV_COLORS[u.color] || '#C9A84C';
                  return (
                    <tr key={u.key}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <div style={{ width: 34, height: 34, borderRadius: '50%', background: avatarBg, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, overflow: 'hidden', flexShrink: 0 }}>
                            {u.photo_url ? <img src={api.assetUrl(u.photo_url)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="" /> : u.initials}
                          </div>
                          <div>
                            <div style={{ fontWeight: 600, fontSize: 13 }}>{u.name}</div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>@{u.key}</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ fontSize: 13 }}>{u.role}<br /><span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{u.dept}</span></td>
                      <td>
                        <span className={`access-badge ${LEVEL_BADGE_CLASS[u.level] || 'badge-dourado'}`} style={{ fontSize: 10 }}>
                          {LEVEL_LABEL[u.level]}
                        </span>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>
                          Nível {u.access_level}
                          {u.is_admin ? ' · SuperAdmin' : u.is_admin_user ? ' · Admin' : ''}
                          {u.is_rh ? ' · RH' : ''}
                        </div>
                      </td>
                      <td style={{ fontWeight: 700, color: 'var(--gold)', fontSize: 14 }}>{u.points}</td>
                      <td>
                        {u.password_changed === 0 || u.password_changed === false
                          ? <span style={{ fontSize: 11, color: '#f59e0b', fontWeight: 600 }}>⏳ Pendente troca</span>
                          : <span style={{ fontSize: 11, color: '#22c55e', fontWeight: 600 }}>✅ Definida</span>}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 5 }}>
                          {manageable && (
                            <>
                              <button className="btn-admin btn-secondary" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => openEdit(u)}>✏️</button>
                              <button className="btn-admin btn-secondary" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => { setShowResetModal(u); setResetPass(''); }} title="Resetar senha">🔑</button>
                              <button className="btn-admin btn-danger" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => deleteUser(u.key)}>🗑️</button>
                            </>
                          )}
                          {!manageable && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>—</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── LOGS TAB ── */}
      {tab === 'Logs de Segurança' && (
        <div>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
            Registro de todas as ações administrativas de segurança.
          </p>
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            {logs.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                <div style={{ fontSize: 36, marginBottom: 8 }}>📋</div>
                <p>Nenhum evento registrado ainda.</p>
              </div>
            ) : logs.map(log => (
              <div key={log.id} className="log-row">
                <span className={`log-type ${log.action_type.includes('Reset') ? 'reset' : log.action_type.includes('Criação') ? 'create' : ''}`}>
                  {log.action_type}
                </span>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 600 }}>{log.actor_key}</span>
                  {log.target_key && log.target_key !== log.actor_key && (
                    <> → <span style={{ color: 'var(--text-muted)' }}>{log.target_key}</span></>
                  )}
                  {log.details && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{log.details}</div>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {timeAgo(log.created_at)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── USER MODAL ── */}
      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal-card" style={{ maxWidth: 600 }}>
            <div className="modal-header">
              <div className="modal-title">{editingUser ? 'Editar Colaborador' : 'Adicionar Colaborador'}</div>
              <button className="modal-close" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <div className="admin-form">
              {!editingUser && (
                <div className="admin-form-row">
                  <div className="admin-field">
                    <label>Login (chave única, sem espaços)</label>
                    <input type="text" value={f.key} onChange={e => setF('key', e.target.value.toLowerCase().replace(/\s/g,''))} placeholder="Ex: joaosilva" />
                  </div>
                  <div className="admin-field">
                    <label>Senha temporária</label>
                    <input type="text" value={f.password} onChange={e => setF('password', e.target.value)} placeholder="Usuário trocará no 1º acesso" />
                  </div>
                </div>
              )}
              <div className="admin-form-row">
                <div className="admin-field">
                  <label>Nome completo</label>
                  <input type="text" value={f.name} onChange={e => setF('name', e.target.value)} placeholder="Ex: Maria da Silva" />
                </div>
                <div className="admin-field">
                  <label>Iniciais (2–3 letras)</label>
                  <input type="text" value={f.initials} onChange={e => setF('initials', e.target.value.toUpperCase())} placeholder="Ex: MS" maxLength={3} />
                </div>
              </div>
              <div className="admin-form-row">
                <div className="admin-field">
                  <label>Cargo</label>
                  <input type="text" value={f.role} onChange={e => setF('role', e.target.value)} placeholder="Ex: Psicóloga" />
                </div>
                <div className="admin-field">
                  <label>Setor</label>
                  <input type="text" value={f.dept} onChange={e => setF('dept', e.target.value)} placeholder="Ex: Psicologia" />
                </div>
              </div>
              <div className="admin-form-row">
                <div className="admin-field">
                  <label>Nível de acesso (badge)</label>
                  <select value={f.level} onChange={e => setF('level', e.target.value)}>
                    <option value="dourado">🟡 Dourado</option>
                    <option value="platina">⬜ Platina</option>
                    <option value="diamante">💎 Diamante</option>
                  </select>
                </div>
                <div className="admin-field">
                  <label>Nível de poder (RBAC)</label>
                  <select value={f.access_level} onChange={e => setF('access_level', parseInt(e.target.value))}
                    disabled={!isLevel3}>
                    <option value={0}>0 — Funcionário</option>
                    <option value={1}>1 — Funcionário Sênior</option>
                    {isLevel3 && <option value={2}>2 — Admin User (Liderança)</option>}
                    {isLevel3 && <option value={3}>3 — Admin Server</option>}
                  </select>
                </div>
              </div>
              <div className="admin-form-row">
                <div className="admin-field">
                  <label>Cor do avatar</label>
                  <select value={f.color} onChange={e => setF('color', e.target.value)}>
                    <option value="av-gold">Dourado</option>
                    <option value="av-teal">Verde</option>
                    <option value="av-coral">Coral</option>
                    <option value="av-blue">Azul</option>
                    <option value="av-pink">Rosa</option>
                    <option value="av-purple">Roxo</option>
                    <option value="av-green">Verde escuro</option>
                    <option value="av-amber">Âmbar</option>
                  </select>
                </div>
                <div className="admin-field">
                  <label>Pontos iniciais</label>
                  <input type="number" value={f.points} onChange={e => setF('points', parseInt(e.target.value) || 0)} min={0} />
                </div>
              </div>
              <div className="admin-form-row">
                <div className="admin-field">
                  <label>📅 Data de Admissão (Tempo de Casa)</label>
                  <input type="date" value={f.hire_date || ''} onChange={e => setF('hire_date', e.target.value)} />
                </div>
                <div className="admin-field">
                  <label>🏢 Posição no Organograma</label>
                  <select value={f.org_position || 'colaborador'} onChange={e => setF('org_position', e.target.value)}>
                    <option value="colaborador">👤 Colaborador</option>
                    <option value="setor">🏢 Setor</option>
                    <option value="lideranca">⭐ Liderança</option>
                    <option value="diretoria">👑 Diretoria</option>
                  </select>
                </div>
              </div>
              <div className="admin-form-row">
                <div className="admin-field">
                  <label>🏥 Empresa</label>
                  <select value={f.is_orcoma ? 'orcoma' : 'dialogos'} onChange={e => setF('is_orcoma', e.target.value === 'orcoma')}>
                    <option value="dialogos">🏥 Clínica Diálogos</option>
                    <option value="orcoma">🔷 Orcoma</option>
                  </select>
                </div>
              </div>
              <div className="admin-field">
                <label>Permissões especiais</label>
                {[
                  { key: 'is_rh', label: '🧬 Permissão RH — acessa pasta de Recursos Humanos' },
                  { key: 'is_admin_user', label: '🛠 Admin Usuário — gerencia colaboradores e pastas', disabled: !isLevel3 },
                  { key: 'is_admin', label: '⚙️ Super Admin — acesso total ao sistema', disabled: !isLevel3 },
                  { key: 'is_ouvidor', label: '📢 Ouvidor(a) — acessa todas as reclamações da ouvidoria' },
                  { key: 'is_orcoma', label: '🔷 Funcionário Orcoma — empresa parceira' },
                ].map(opt => (
                  <div className="checkbox-row" key={opt.key}>
                    <input type="checkbox" id={opt.key} checked={!!f[opt.key]} onChange={e => setF(opt.key, e.target.checked)} disabled={opt.disabled} />
                    <label htmlFor={opt.key} style={{ color: opt.disabled ? 'var(--text-muted)' : 'var(--text)' }}>{opt.label}</label>
                  </div>
                ))}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-admin btn-secondary" onClick={() => setShowModal(false)}>Cancelar</button>
              <button className="btn-admin btn-primary" onClick={saveUser} disabled={saving}>
                {saving ? 'Salvando...' : 'Salvar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── RESET PASSWORD MODAL ── */}
      {showResetModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowResetModal(null)}>
          <div className="modal-card" style={{ maxWidth: 420 }}>
            <div className="modal-header">
              <div className="modal-title">🔑 Resetar Senha</div>
              <button className="modal-close" onClick={() => setShowResetModal(null)}>✕</button>
            </div>
            <div style={{ marginBottom: 16 }}>
              <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                Você está resetando a senha de <strong>{showResetModal.name}</strong>.
                Defina uma senha temporária — o usuário será obrigado a trocá-la no próximo acesso.
              </p>
            </div>
            <div className="admin-field">
              <label>Nova senha temporária</label>
              <input type="text" value={resetPass} onChange={e => setResetPass(e.target.value)} placeholder="Mínimo 4 caracteres" autoFocus />
            </div>
            <div style={{ padding: '12px 0 4px', fontSize: 12, color: '#f59e0b' }}>
              ⚠️ Esta ação será registrada no log de auditoria.
            </div>
            <div className="modal-footer">
              <button className="btn-admin btn-secondary" onClick={() => setShowResetModal(null)}>Cancelar</button>
              <button className="btn-admin btn-primary" onClick={doReset}>Confirmar Reset</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
