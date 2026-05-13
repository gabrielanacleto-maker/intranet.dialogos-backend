import { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import {
  AV_COLORS, LEVEL_LABEL, LEVEL_BADGE_CLASS,
  getRoleClass, getRoleGlowClass, getTenureLabel, getTenureClass, getRoleStyle
} from '../utils';
import { RomanticAvatarDecoration } from './TemasComemorativos';
import { GifPicker, MentionSuggest, renderTextMedia } from '../components/TextTools';

const MAX_TEXT = 20000;
const MAX_IMAGE_SIZE = 5 * 1024 * 1024;
const MAX_VIDEO_SIZE = 25 * 1024 * 1024;
const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const GIF_TYPES = ['image/gif'];
const VIDEO_TYPES = ['video/mp4', 'video/webm', 'video/quicktime'];

export function openColleagueProfile(userKey) {
  if (!userKey) return;
  window.history.pushState({}, '', `/colleague/${encodeURIComponent(userKey)}`);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function companyOf(user) {
  return user?.company || (user?.is_orcoma ? 'Orcoma Contabilidade' : 'Clínica Diálogos');
}

function ProfileAvatar({ profileUser, size = 96 }) {
  const [broken, setBroken] = useState(false);
  const photoUrl = profileUser?.photo_url ? api.assetUrl(profileUser.photo_url) : null;
  const bg = AV_COLORS[profileUser?.color] || '#C9A84C';
  const avatar = (
    <div style={{ width: size, height: size, borderRadius: '50%', border: '3px solid var(--gold)', background: photoUrl && !broken ? 'transparent' : bg, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', boxShadow: '0 0 24px rgba(201,168,76,0.25)' }}>
      {photoUrl && !broken
        ? <img src={photoUrl} alt={profileUser.name} onError={() => setBroken(true)} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        : <span style={{ fontFamily: 'Playfair Display', fontSize: size * 0.34, fontWeight: 700, color: '#fff' }}>{profileUser?.initials || '?'}</span>}
    </div>
  );
  return <RomanticAvatarDecoration>{avatar}</RomanticAvatarDecoration>;
}

export function UserAvatar({ photoUrl, name, size = 48, onClick }) {
  const [broken, setBroken] = useState(false);
  const initials = name?.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase() || '?';
  const avatar = (
    <button onClick={onClick} type="button" style={{ width: size, height: size, borderRadius: '50%', border: '2px solid var(--gold)', overflow: 'hidden', flexShrink: 0, background: '#2A2618', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: onClick ? 'pointer' : 'default', padding: 0 }}>
      {photoUrl && !broken
        ? <img src={photoUrl} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={() => setBroken(true)} />
        : <span style={{ fontSize: size * 0.35, fontWeight: 700, color: 'var(--gold)' }}>{initials}</span>}
    </button>
  );
  return <RomanticAvatarDecoration>{avatar}</RomanticAvatarDecoration>;
}

function ProfileBackground({ profileUser, children }) {
  const company = companyOf(profileUser);
  const isOrcoma = company === 'Orcoma Contabilidade';
  return (
    <div style={{ position: 'relative', overflow: 'hidden', background: isOrcoma ? '#06169d' : 'linear-gradient(135deg, #2A2618 0%, #1C1A14 100%)', borderRadius: 'var(--radius)', padding: 32, textAlign: 'center', marginBottom: 20, border: '1px solid rgba(201,168,76,0.2)' }}>
      <div style={{ position: 'absolute', inset: 0, background: isOrcoma ? 'linear-gradient(135deg, rgba(0,24,160,0.45), rgba(0,0,0,0.72))' : 'rgba(0,0,0,0.42)', zIndex: 1 }} />
      <div style={{ position: 'absolute', inset: 0, backgroundImage: isOrcoma ? 'none' : 'url(/logo.png.png)', backgroundRepeat: 'no-repeat', backgroundPosition: 'center', backgroundSize: 'contain', opacity: isOrcoma ? 0 : 0.36, zIndex: 0 }} />
      {isOrcoma && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.36, color: '#fff', fontSize: 42, fontWeight: 800, letterSpacing: 1, zIndex: 0 }}>
          ORCOMA
        </div>
      )}
      <div style={{ position: 'relative', zIndex: 2 }}>{children}</div>
    </div>
  );
}

function Badges({ profileUser }) {
  return (
    <div style={{ display: 'flex', gap: 6, justifyContent: 'center', flexWrap: 'wrap' }}>
      <span className={`access-badge ${LEVEL_BADGE_CLASS[profileUser.level] || 'badge-dourado'}`}>{LEVEL_LABEL[profileUser.level] || profileUser.level}</span>
      {!!profileUser.is_rh && <span className="access-badge badge-rh">RH</span>}
      {!!profileUser.is_ouvidor && <span className="access-badge badge-ouvidor">Ouvidor</span>}
      {!!profileUser.is_admin_user && !profileUser.is_admin && <span className="access-badge badge-admin-user">Admin User</span>}
      {!!profileUser.is_admin && <span className="access-badge badge-super-admin">Admin System</span>}
      {!!profileUser.is_orcoma && <span className="access-badge badge-orcoma">Orcoma</span>}
    </div>
  );
}

export function ProfileHero({ profileUser, photo, onPhotoUpload, uploading, isOwnProfile }) {
  const roleStyle = getRoleStyle(profileUser.role, profileUser.is_rh, profileUser.is_admin);
  const tenureLabel = getTenureLabel(profileUser.hire_date);
  return (
    <ProfileBackground profileUser={profileUser}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
        <ProfileAvatar profileUser={{ ...profileUser, photo_url: photo || profileUser.photo_url }} />
        {isOwnProfile && onPhotoUpload && (
          <label className="change-photo-btn" style={{ cursor: uploading ? 'wait' : 'pointer' }}>
            {uploading ? 'Enviando...' : 'Alterar Foto'}
            <input type="file" accept="image/*" hidden onChange={onPhotoUpload} />
          </label>
        )}
        <div>
          <div style={{ fontFamily: 'Playfair Display', fontSize: 22, color: '#E8E0CC', fontWeight: 600, marginBottom: 4 }}>{profileUser.name}</div>
          <div className={`profile-role ${getRoleClass(profileUser.role)} ${getRoleGlowClass(profileUser.role, profileUser.dept)}`} style={{ marginBottom: 4, ...roleStyle }}>{profileUser.role}</div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.58)', marginBottom: 14 }}>{profileUser.dept}</div>
          <Badges profileUser={profileUser} />
          {tenureLabel && <div className={`tenure-badge ${getTenureClass(profileUser.hire_date)}`} style={{ marginTop: 8 }}>{tenureLabel}</div>}
        </div>
      </div>
    </ProfileBackground>
  );
}

export function InfoGrid({ profileUser }) {
  const items = [
    { label: 'Cargo', value: profileUser.role },
    { label: 'Setor', value: profileUser.dept },
    { label: 'Pontos', value: `⭐ ${profileUser.points ?? 0}` },
    { label: 'Empresa', value: companyOf(profileUser) },
    { label: 'Admissão', value: profileUser.hire_date || 'Não informada' },
    { label: 'Posição', value: profileUser.org_position || 'colaborador' },
  ];
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginBottom: 20 }}>
      {items.map(item => (
        <div key={item.label} className="surface-card" style={{ padding: 16 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 6 }}>{item.label}</div>
          <div style={{ fontSize: 14, fontWeight: 500 }}>{item.value}</div>
        </div>
      ))}
    </div>
  );
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function mediaType(file) {
  if (GIF_TYPES.includes(file.type)) return 'gif';
  if (IMAGE_TYPES.includes(file.type)) return 'image';
  if (VIDEO_TYPES.includes(file.type)) return 'video';
  return '';
}

export function AboutMeSection({ profileUser, canEdit }) {
  const toast = useToast();
  const { allUsers } = useAuth();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => {
    try { return JSON.parse(profileUser.about_me || '') || { text: '', media: [] }; }
    catch { return { text: profileUser.about_me || '', media: [] }; }
  });
  const [saving, setSaving] = useState(false);
  const counts = useMemo(() => ({
    image: draft.media.filter(m => m.type === 'image').length,
    gif: draft.media.filter(m => m.type === 'gif').length,
    video: draft.media.filter(m => m.type === 'video').length,
  }), [draft.media]);

  useEffect(() => {
    try { setDraft(JSON.parse(profileUser.about_me || '') || { text: '', media: [] }); }
    catch { setDraft({ text: profileUser.about_me || '', media: [] }); }
  }, [profileUser.about_me]);

  async function addMedia(files) {
    const next = [...draft.media];
    for (const file of Array.from(files || [])) {
      const type = mediaType(file);
      if (!type) { toast('Tipo de arquivo bloqueado por segurança.', 'error'); continue; }
      if ((type === 'image' || type === 'gif') && file.size > MAX_IMAGE_SIZE) { toast('Imagem/GIF acima de 5MB.', 'error'); continue; }
      if (type === 'video' && file.size > MAX_VIDEO_SIZE) { toast('Vídeo acima de 25MB.', 'error'); continue; }
      const current = next.filter(m => m.type === type).length;
      if ((type === 'image' && current >= 10) || (type === 'gif' && current >= 5) || (type === 'video' && current >= 3)) {
        toast('Limite de mídia atingido.', 'error');
        continue;
      }
      next.push({ id: `${Date.now()}_${file.name}`, type, name: file.name, src: await readFile(file) });
    }
    setDraft(d => ({ ...d, media: next }));
  }

  async function save() {
    setSaving(true);
    try {
      const payload = JSON.stringify({ text: draft.text.slice(0, MAX_TEXT), media: draft.media });
      await api.updateAboutMe(payload);
      setEditing(false);
      toast('Sobre Mim salvo.', 'success');
    } catch (err) {
      toast(err.message || 'Erro ao salvar Sobre Mim.', 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600 }}>Sobre Mim</div>
        {canEdit && <button className="btn-admin btn-secondary" onClick={() => setEditing(v => !v)}>{editing ? 'Cancelar' : 'Editar'}</button>}
      </div>
      {editing ? (
        <>
          <div style={{ position: 'relative' }}>
            <textarea value={draft.text} maxLength={MAX_TEXT} onChange={e => setDraft(d => ({ ...d, text: e.target.value }))} rows={7} style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical', padding: 12, borderRadius: 8, border: '1.5px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }} />
            <MentionSuggest value={draft.text} onChange={value => setDraft(d => ({ ...d, text: value }))} users={Object.values(allUsers || {})} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{draft.text.length}/{MAX_TEXT}</span>
            <label className="btn-admin btn-secondary" style={{ cursor: 'pointer' }}>
              Adicionar mídia
              <input type="file" multiple hidden accept=".jpg,.jpeg,.png,.webp,.gif,.mp4,.webm,.mov,image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime" onChange={e => { addMedia(e.target.files); e.target.value = ''; }} />
            </label>
            <GifPicker onSelect={url => setDraft(d => ({ ...d, text: `${d.text}${d.text ? '\n' : ''}${url}` }))} />
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Imagens {counts.image}/10 · GIFs {counts.gif}/5 · Vídeos {counts.video}/3</span>
            <button className="btn-admin btn-primary" onClick={save} disabled={saving}>{saving ? 'Salvando...' : 'Salvar'}</button>
          </div>
        </>
      ) : (
        <div style={{ color: draft.text || draft.media.length ? 'var(--text)' : 'var(--text-muted)', fontSize: 14, whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
          {draft.text ? renderTextMedia(draft.text) : 'Nenhuma informação adicionada.'}
        </div>
      )}
      {draft.media.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10, marginTop: 14 }}>
          {draft.media.map(media => (
            <div key={media.id} style={{ position: 'relative', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden', background: 'var(--bg)', aspectRatio: '1.3' }}>
              {media.type === 'video'
                ? <video src={media.src} controls style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : <img src={media.src} alt={media.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
              {editing && <button className="btn-admin btn-danger" onClick={() => setDraft(d => ({ ...d, media: d.media.filter(m => m.id !== media.id) }))} style={{ position: 'absolute', top: 6, right: 6, padding: '3px 7px', fontSize: 11 }}>Remover</button>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function InternalReviewsSection({ loggedUser, profileUser }) {
  if (loggedUser?.key !== profileUser?.key) return null;
  const blocks = ['Avaliação do Líder', 'Avaliação do RH', 'Avaliação do Diretor'];
  return (
    <div className="surface-card" style={{ padding: 20, marginBottom: 20 }}>
      <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 14 }}>Avaliações Internas</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
        {blocks.map(title => (
          <div key={title} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 14, background: 'var(--bg)' }}>
            <div style={{ fontWeight: 700, marginBottom: 10 }}>{title}</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.7 }}>
              <div><strong>Positivas:</strong> Não registrada.</div>
              <div><strong>Negativas:</strong> Não registrada.</div>
              <div><strong>Feedback:</strong> Nenhum feedback salvo.</div>
              <div><strong>Data:</strong> Não informada.</div>
              <div><strong>Avaliador:</strong> Não informado.</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ColleagueProfilePage({ profileKey }) {
  const { user, allUsers } = useAuth();
  const [profileUser, setProfileUser] = useState(null);
  const [manager, setManager] = useState(null);
  const [teamData, setTeamData] = useState(null);

  useEffect(() => {
    async function load() {
      const users = Object.keys(allUsers || {}).length ? Object.values(allUsers) : await api.getUsers();
      const found = users.find(u => u.key === profileKey);
      setProfileUser(found || null);
      if (found) {
        const [managerRes, teamRes] = await Promise.all([
          api.getUserManager(found.key).catch(() => ({ manager: null })),
          api.getUserTeam(found.key).catch(() => ({ members: [] })),
        ]);
        setManager(managerRes.manager || null);
        setTeamData(teamRes);
      }
    }
    load();
  }, [profileKey, allUsers]);

  if (!profileUser) return <div style={{ padding: 40, color: 'var(--text-muted)' }}>Perfil não encontrado.</div>;

  return (
    <div>
      <div className="section-title">Perfil do Colaborador</div>
      <ProfileHero profileUser={profileUser} isOwnProfile={false} />
      <InfoGrid profileUser={profileUser} />
      <ProfileRelations manager={manager} teamData={teamData} profileUser={profileUser} />
      <AboutMeSection profileUser={profileUser} canEdit={user?.key === profileUser.key} />
      <InternalReviewsSection loggedUser={user} profileUser={profileUser} />
    </div>
  );
}

export function ProfileRelations({ manager, teamData, profileUser, canEditManager, onEditManager, editingManager, gestores = [], selectedManagerKey, setSelectedManagerKey, saveManager, savingManager }) {
  const orgPosition = profileUser.org_position || 'colaborador';
  const showManager = orgPosition !== 'gestor';
  const teamLabel = orgPosition === 'colaborador' ? 'Sua Equipe' : 'Subordinados';
  const inputStyle = { width: '100%', padding: 10, marginBottom: 10, borderRadius: 8, background: 'var(--bg)', color: 'var(--text)', border: '1.5px solid var(--border)', fontFamily: 'inherit', fontSize: 14 };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: showManager ? '1fr 1fr' : '1fr', gap: 14, marginBottom: 20 }}>
      {showManager && (
        <div className="surface-card" style={{ padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600 }}>Seu Gestor</div>
            {canEditManager && <button className="btn-admin btn-secondary" onClick={onEditManager}>Editar</button>}
          </div>
          {manager ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <UserAvatar photoUrl={manager.photo_url ? api.assetUrl(manager.photo_url) : null} name={manager.name} size={56} onClick={() => openColleagueProfile(manager.key)} />
              <button type="button" onClick={() => openColleagueProfile(manager.key)} style={{ textAlign: 'left', background: 'none', border: 0, color: 'inherit', cursor: 'pointer', padding: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{manager.name}</div>
                <div style={{ fontSize: 13, color: 'var(--text-muted)', ...getRoleStyle(manager.role, false, false) }}>{manager.role}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', opacity: 0.7 }}>{manager.dept}</div>
              </button>
            </div>
          ) : <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Não definido</div>}
          {editingManager && (
            <div style={{ marginTop: 16 }}>
              <select value={selectedManagerKey} onChange={e => setSelectedManagerKey(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
                <option value="">Sem gestor</option>
                {gestores.map(g => <option key={g.key} value={g.key}>{g.name} ({g.role})</option>)}
              </select>
              <button className="btn-admin btn-primary" onClick={saveManager} disabled={savingManager} style={{ width: '100%' }}>{savingManager ? 'Salvando...' : 'Salvar Gestor'}</button>
            </div>
          )}
        </div>
      )}
      <div className="surface-card" style={{ padding: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 14 }}>{teamLabel}</div>
        {teamData && teamData.members.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 300, overflowY: 'auto' }}>
            {teamData.members.map(member => (
              <div key={member.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 8, background: 'rgba(201,168,76,0.05)', border: '1px solid rgba(201,168,76,0.12)' }}>
                <UserAvatar photoUrl={member.photo_url ? api.assetUrl(member.photo_url) : null} name={member.name} size={40} onClick={() => openColleagueProfile(member.key)} />
                <button type="button" onClick={() => openColleagueProfile(member.key)} style={{ minWidth: 0, textAlign: 'left', background: 'none', border: 0, color: 'inherit', cursor: 'pointer', padding: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{member.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{member.role}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', opacity: 0.7 }}>{member.dept}</div>
                </button>
              </div>
            ))}
          </div>
        ) : <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Nenhum vínculo definido.</div>}
      </div>
    </div>
  );
}
