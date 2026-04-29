import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { AV_COLORS, getTenureClass, getTenureLabel, getRoleGlowClass, LEVEL_BADGE_CLASS, timeAgo } from '../utils';

function UserAvatar({ u, size = 36 }) {
  const photoUrl = u.photo_url ? api.assetUrl(u.photo_url) : null;
  const bg = AV_COLORS[u.color] || '#C9A84C';
  const tenureClass = getTenureClass(u.hire_date);
  return (
    <div className={`team-avatar-wrap ${tenureClass}`} style={{ width: size, height: size, display: 'inline-block', flexShrink: 0 }}>
      <div className="team-avatar" style={{ width: size, height: size, background: photoUrl ? 'transparent' : bg }}>
        {photoUrl
          ? <img src={photoUrl} alt={u.name} style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} onError={e => e.target.style.display = 'none'} />
          : <span style={{ fontSize: size * 0.38, color: '#fff', fontWeight: 700 }}>{u.initials}</span>}
      </div>
    </div>
  );
}

function UserMiniCard({ u, onChat, onProfile }) {
  const glowClass = getRoleGlowClass(u.role, u.dept);
  const tenureLabel = getTenureLabel(u.hire_date);
  const tenureClass = getTenureClass(u.hire_date);

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
      borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg)',
      marginBottom: 6, cursor: 'pointer', transition: 'all 0.15s',
    }}
      onMouseEnter={e => e.currentTarget.style.background = 'var(--surface)'}
      onMouseLeave={e => e.currentTarget.style.background = 'var(--bg)'}
    >
      <UserAvatar u={u} size={36} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.name}</div>
        <div className={`team-role ${glowClass}`} style={{ fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.role}</div>
        {tenureLabel && <div className={`tenure-badge ${tenureClass}`} style={{ marginTop: 2, fontSize: 10, display: 'inline-block' }}>{tenureLabel}</div>}
        <div style={{ display: 'flex', gap: 4, marginTop: 3, flexWrap: 'wrap' }}>
          {!!u.is_rh && <span className="access-badge badge-rh" style={{ fontSize: 9, padding: '1px 5px' }}>🧬 RH</span>}
          {!!u.is_ouvidor && <span className="access-badge badge-ouvidor" style={{ fontSize: 9, padding: '1px 5px' }}>👁️</span>}
          {!!u.is_admin && <span className="access-badge badge-super-admin" style={{ fontSize: 9, padding: '1px 5px' }}>⚡</span>}
          {!!u.is_orcoma && <span className="access-badge badge-orcoma" style={{ fontSize: 9, padding: '1px 5px' }}>🔷</span>}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <button onClick={e => { e.stopPropagation(); onChat(u); }} style={{ background: 'var(--gold)', color: '#fff', border: 'none', borderRadius: 6, padding: '3px 8px', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }}>💬</button>
        <button onClick={e => { e.stopPropagation(); onProfile(u); }} style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '3px 8px', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }}>👤</button>
      </div>
    </div>
  );
}

const REACTIONS = ['❤️', '👍', '😂', '😮', '😢', '🔥', '🎉', '👏'];
const EMOJI_LIST = ['😀','😂','🥰','😎','🤔','😅','🙏','👍','🔥','❤️','🎉','✅','💯','🚀','⭐','💪','😄','🤣','😊','😍','😒','😢','😡','👋','✌️','🤝','👀','💡','📌','🎯','🎨','💼','📅','🏥','💊','🩺','🧬','📋','✏️','📢','🔒','🌟','⚡','🛡️','👑','💎','🟡','⬜'];

function ChatWindow({ targetUser, currentUser, onClose }) {
  const roomId = [currentUser.key, targetUser.key].sort().join('_');
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [showEmoji, setShowEmoji] = useState(false);
  const [reactions, setReactions] = useState({});
  const bottomRef = useRef(null);
  const pollRef = useRef(null);

  useEffect(() => {
    loadMessages();
    pollRef.current = setInterval(loadMessages, 3000);
    return () => clearInterval(pollRef.current);
  }, [roomId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function loadMessages() {
    try {
      const data = await api.getChat(roomId);
      setMessages(data);
    } catch {}
  }

  async function send() {
    if (!text.trim() || sending) return;
    setSending(true);
    try {
      await api.sendChat(roomId, text.trim());
      setText('');
      await loadMessages();
    } catch (e) { alert(e.message); }
    finally { setSending(false); }
  }

  function addReaction(msgId, emoji) {
    setReactions(prev => {
      const curr = prev[msgId] || {};
      return { ...prev, [msgId]: { ...curr, [emoji]: (curr[emoji] || 0) + 1 } };
    });
  }

  const photoUrl = targetUser.photo_url ? api.assetUrl(targetUser.photo_url) : null;
  const bg = AV_COLORS[targetUser.color] || '#C9A84C';

  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 300, width: 340, height: 480,
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 16,
      boxShadow: '0 8px 40px rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column', zIndex: 9000,
    }}>
      {/* Chat header */}
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10, background: 'var(--sidebar-bg)', borderRadius: '16px 16px 0 0' }}>
        <div style={{ width: 36, height: 36, borderRadius: '50%', overflow: 'hidden', background: photoUrl ? 'transparent' : bg, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 14 }}>
          {photoUrl ? <img src={photoUrl} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : targetUser.initials}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>{targetUser.name}</div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{targetUser.role}</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', fontSize: 16 }}>✕</button>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, marginTop: 40 }}>
            👋 Inicie a conversa!
          </div>
        )}
        {messages.map(msg => {
          const isMine = msg.sender_key === currentUser.key;
          const msgReactions = reactions[msg.id] || {};
          return (
            <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', alignItems: isMine ? 'flex-end' : 'flex-start' }}>
              <div
                style={{
                  maxWidth: '80%', padding: '8px 12px', borderRadius: isMine ? '14px 14px 4px 14px' : '14px 14px 14px 4px',
                  background: isMine ? 'var(--gold)' : 'var(--bg)',
                  color: isMine ? '#fff' : 'var(--text)', fontSize: 13, lineHeight: 1.5,
                  border: isMine ? 'none' : '1px solid var(--border)',
                  wordBreak: 'break-word',
                }}
                title={timeAgo(msg.created_at)}
              >
                {msg.text}
              </div>
              {/* Reaction row */}
              <div style={{ display: 'flex', gap: 4, marginTop: 3, flexWrap: 'wrap', justifyContent: isMine ? 'flex-end' : 'flex-start' }}>
                {Object.entries(msgReactions).map(([emoji, count]) => (
                  <span key={emoji} onClick={() => addReaction(msg.id, emoji)} style={{ background: 'var(--bg)', borderRadius: 10, padding: '1px 6px', fontSize: 11, cursor: 'pointer', border: '1px solid var(--border)' }}>
                    {emoji} {count}
                  </span>
                ))}
                <span
                  onClick={() => {
                    const emoji = REACTIONS[Math.floor(Math.random() * REACTIONS.length)];
                    addReaction(msg.id, emoji);
                  }}
                  style={{ opacity: 0.4, cursor: 'pointer', fontSize: 12 }}
                >+</span>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Emoji picker */}
      {showEmoji && (
        <div style={{
          position: 'absolute', bottom: 56, left: 8, right: 8, background: 'var(--surface)',
          border: '1px solid var(--border)', borderRadius: 12, padding: 10,
          display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 140, overflowY: 'auto', zIndex: 10,
          boxShadow: '0 4px 20px rgba(0,0,0,0.2)',
        }}>
          {EMOJI_LIST.map(e => (
            <span key={e} onClick={() => { setText(t => t + e); setShowEmoji(false); }} style={{ fontSize: 20, cursor: 'pointer', padding: '2px 4px', borderRadius: 6, transition: 'background 0.1s' }}
              onMouseEnter={ev => ev.target.style.background = 'var(--bg)'}
              onMouseLeave={ev => ev.target.style.background = 'transparent'}
            >{e}</span>
          ))}
        </div>
      )}

      {/* Input */}
      <div style={{ padding: '8px 10px', borderTop: '1px solid var(--border)', display: 'flex', gap: 6, alignItems: 'center' }}>
        <button onClick={() => setShowEmoji(v => !v)} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', padding: '0 2px' }}>😊</button>
        <input
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Digite uma mensagem..."
          style={{ flex: 1, padding: '8px 12px', borderRadius: 20, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13, fontFamily: 'inherit', outline: 'none' }}
        />
        <button
          onClick={send}
          disabled={!text.trim() || sending}
          style={{
            background: text.trim() ? 'var(--gold)' : 'var(--border)', color: '#fff',
            border: 'none', borderRadius: '50%', width: 34, height: 34, display: 'flex',
            alignItems: 'center', justifyContent: 'center', cursor: text.trim() ? 'pointer' : 'default', fontSize: 16,
          }}
        >➤</button>
      </div>
    </div>
  );
}

function ProfileModal({ targetUser, currentUser, onClose, onChat }) {
  const [likes, setLikes] = useState({ heart: 0, thumbs: 0, star: 0 });
  const [myLikes, setMyLikes] = useState({});
  const glowClass = getRoleGlowClass(targetUser.role, targetUser.dept);
  const tenureLabel = getTenureLabel(targetUser.hire_date);
  const tenureClass = getTenureClass(targetUser.hire_date);

  function doLike(type) {
    if (myLikes[type]) return;
    setLikes(prev => ({ ...prev, [type]: prev[type] + 1 }));
    setMyLikes(prev => ({ ...prev, [type]: true }));
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 380, textAlign: 'center' }}>
        <div className="modal-header">
          <h3>👤 Perfil</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
          <div className={`team-avatar-wrap ${tenureClass}`} style={{ width: 90, height: 90 }}>
            <div className="team-avatar" style={{ width: 90, height: 90, background: targetUser.photo_url ? 'transparent' : (AV_COLORS[targetUser.color] || '#C9A84C') }}>
              {targetUser.photo_url
                ? <img src={api.assetUrl(targetUser.photo_url)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} />
                : <span style={{ fontSize: 32, color: '#fff', fontWeight: 700 }}>{targetUser.initials}</span>}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{targetUser.name}</div>
            <div className={`team-role ${glowClass}`} style={{ fontSize: 14, marginTop: 2 }}>{targetUser.role}</div>
            {targetUser.dept && <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>{targetUser.dept}</div>}
          </div>
          {tenureLabel && <div className={`tenure-badge ${tenureClass}`}>{tenureLabel}</div>}
          {/* Reactions */}
          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            {[['heart', '❤️', 'Curtir'], ['thumbs', '👍', 'Top!'], ['star', '⭐', 'Estrela']].map(([k, emoji, label]) => (
              <button key={k} onClick={() => doLike(k)} style={{
                background: myLikes[k] ? 'rgba(212,168,67,0.15)' : 'var(--bg)',
                border: `1px solid ${myLikes[k] ? 'var(--gold)' : 'var(--border)'}`,
                borderRadius: 12, padding: '6px 14px', cursor: myLikes[k] ? 'default' : 'pointer',
                display: 'flex', flexDirection: 'column', alignItems: 'center', fontFamily: 'inherit',
              }}>
                <span style={{ fontSize: 22 }}>{emoji}</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{likes[k]}</span>
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn-admin btn-primary" onClick={() => { onClose(); onChat(targetUser); }}>💬 Iniciar Conversa</button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function TeamWidget() {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [chatWith, setChatWith] = useState(null);
  const [profileOf, setProfileOf] = useState(null);

  useEffect(() => {
    api.getUsers().then(data => setUsers(data.filter(u => u.key !== user.key))).catch(() => {});
  }, []);

  const filtered = users.filter(u =>
    [u.name, u.role, u.dept].join(' ').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="widget" style={{ padding: 0 }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
        <div className="widget-title" style={{ marginBottom: 8 }}>👥 Colaboradores</div>
        <input
          placeholder="🔍 Buscar..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: '100%', padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 12, fontFamily: 'inherit', outline: 'none' }}
        />
      </div>
      <div style={{ padding: '10px 14px', maxHeight: 320, overflowY: 'auto' }}>
        {filtered.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>Nenhum encontrado</div>
        ) : (
          filtered.map(u => (
            <UserMiniCard
              key={u.key}
              u={u}
              onChat={setChatWith}
              onProfile={setProfileOf}
            />
          ))
        )}
      </div>

      {chatWith && (
        <ChatWindow
          targetUser={chatWith}
          currentUser={user}
          onClose={() => setChatWith(null)}
        />
      )}
      {profileOf && (
        <ProfileModal
          targetUser={profileOf}
          currentUser={user}
          onClose={() => setProfileOf(null)}
          onChat={u => { setProfileOf(null); setChatWith(u); }}
        />
      )}
    </div>
  );
}
