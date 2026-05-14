import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { AV_COLORS, getTenureClass, getTenureLabel, getRoleGlowClass, timeAgo } from '../utils';
import { openColleagueProfile } from '../pages/ColleagueProfilePage';

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
      onClick={() => onProfile(u)}
      onMouseEnter={e => e.currentTarget.style.background = 'var(--surface)'}
      onMouseLeave={e => e.currentTarget.style.background = 'var(--bg)'}
    >
      <UserAvatar u={u} size={36} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.name}</div>
        <div className={`team-role ${glowClass}`} style={{ fontSize: 11, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{u.role}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <button onClick={e => { e.stopPropagation(); onChat(u); }} style={{ background: 'var(--gold)', color: '#fff', border: 'none', borderRadius: 6, padding: '3px 8px', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }}>Chat</button>
        <button onClick={e => { e.stopPropagation(); onProfile(u); }} style={{ background: 'var(--surface)', color: 'var(--text)', border: '1px solid var(--border)', borderRadius: 6, padding: '3px 8px', fontSize: 11, cursor: 'pointer', fontFamily: 'inherit' }}>Perfil</button>
      </div>
    </div>
  );
}

const REACTIONS = ['❤️', '👍', '😂', '😮', '😢', '🔥', '🎉', '👏'];
const EMOJI_LIST = ['😀','😂','🥰','😎','🤔','😅','🙏','👍','🔥','❤️','🎉','✅','💯','🚀','⭐','💪','😄','🤣','😊','😍','😒','😢','😡','👋','✌️','🤝','👀','💡','📌','🎯','🎨','💼','📅','🏥','💊','🩺','🧬','📋','✏️','📢','🔒','🌟','⚡','🛡️','👑','💎','🟡','⬜'];

function ChatWindow({ targetUser, currentUser, onClose, onMinimize }) {
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
      position: 'fixed', bottom: 60, right: 300, width: 340, height: 480,
      background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 16,
      boxShadow: '0 8px 40px rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column', zIndex: 9000,
    }}>
      {/* Chat header with controls */}
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 10, background: 'var(--sidebar-bg)', borderRadius: '16px 16px 0 0' }}>
        <div style={{ width: 36, height: 36, borderRadius: '50%', overflow: 'hidden', background: photoUrl ? 'transparent' : bg, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 14 }}>
          {photoUrl ? <img src={photoUrl} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : targetUser.initials}
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>{targetUser.name}</div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>{targetUser.role}</div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={onMinimize} title="Minimizar" style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 16, width: 28, height: 28, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>−</button>
          <button onClick={onClose} title="Fechar" style={{ background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', cursor: 'pointer', fontSize: 14, width: 28, height: 28, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
        </div>
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

function MinimizedChat({ u, unread, onRestore, onCloseMinimized }) {
  const photoUrl = u.photo_url ? api.assetUrl(u.photo_url) : null;
  const bg = AV_COLORS[u.color] || '#C9A84C';
  const hasUnread = (unread || 0) > 0;
  return (
    <div
      onClick={() => onRestore(u)}
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '5px 10px', borderRadius: 10,
        background: hasUnread ? 'var(--gold)' : 'var(--bg)',
        border: hasUnread ? '2px solid #ff2d7a' : '1px solid var(--border)',
        cursor: 'pointer', fontSize: 12,
        animation: hasUnread ? 'pulse 2s infinite' : 'none',
        position: 'relative',
      }}
    >
      <div style={{ width: 22, height: 22, borderRadius: '50%', overflow: 'hidden', background: photoUrl ? 'transparent' : bg, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 9, flexShrink: 0 }}>
        {photoUrl ? <img src={photoUrl} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : u.initials}
      </div>
      <span style={{ fontWeight: hasUnread ? 700 : 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 70 }}>{u.name}</span>
      {hasUnread && (
        <span style={{
          background: '#ef4444', color: '#fff', fontSize: 10, fontWeight: 700,
          borderRadius: '50%', minWidth: 18, height: 18,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: '0 4px',
        }}>{unread}</span>
      )}
      <button
        onClick={e => { e.stopPropagation(); onCloseMinimized(u); }}
        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: hasUnread ? '#fff' : 'var(--text-muted)', padding: '0 2px', lineHeight: 1 }}
      >✕</button>
    </div>
  );
}

export default function TeamWidget() {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');
  const [activeChat, setActiveChat] = useState(null);
  const [minimizedChats, setMinimizedChats] = useState([]);
  const [unreadCounts, setUnreadCounts] = useState({});
  const knownRoomsRef = useRef(new Set());
  const activeChatRef = useRef(activeChat);
  activeChatRef.current = activeChat;
  const minimizedRef = useRef(minimizedChats);
  minimizedRef.current = minimizedChats;
  const usersRef = useRef(users);
  usersRef.current = users;

  useEffect(() => {
    api.getUsers().then(data => setUsers(data.filter(u => u.key !== user.key))).catch(() => {});
  }, []);

  // Poll for new conversations every 3s
  useEffect(() => {
    if (!user?.key) return;
    let initialized = false;
    async function pollRecent() {
      try {
        const rooms = await api.getRecentChats();
        const known = knownRoomsRef.current;
        const isFirst = !initialized;
        for (const room of rooms) {
          if (isFirst) {
            known.add(room.room_id);
            continue;
          }
          if (known.has(room.room_id)) continue;
          known.add(room.room_id);
          const isFromMe = room.last_sender_key === user.key;
          const otherUser = usersRef.current.find(u => u.key === room.other_key);
          if (!otherUser) continue;
          if (!isFromMe) {
            // New incoming conversation from other user — auto-open
            const cur = activeChatRef.current;
            const minimized = minimizedRef.current;
            if (cur?.key !== room.other_key && !minimized.find(c => c.key === room.other_key)) {
              setActiveChat(otherUser);
            }
          }
          // Bump unread if chat is not active
          const cur = activeChatRef.current;
          if (cur?.key !== room.other_key) {
            setUnreadCounts(prev => ({ ...prev, [room.other_key]: (prev[room.other_key] || 0) + 1 }));
          }
        }
        initialized = true;
      } catch {}
    }
    pollRecent();
    const interval = setInterval(pollRecent, 3000);
    return () => clearInterval(interval);
  }, [user?.key]);

  // Track activeChat changes to reset unread
  useEffect(() => {
    if (activeChat) {
      setUnreadCounts(prev => ({ ...prev, [activeChat.key]: 0 }));
    }
  }, [activeChat?.key]);

  const filtered = users.filter(u =>
    [u.name, u.role, u.dept].join(' ').toLowerCase().includes(search.toLowerCase())
  );

  function handleOpenChat(targetUser) {
    if (activeChat?.key === targetUser.key) return;
    // Remove from minimized if present
    setMinimizedChats(prev => prev.filter(c => c.key !== targetUser.key));
    setActiveChat(targetUser);
    setUnreadCounts(prev => ({ ...prev, [targetUser.key]: 0 }));
  }

  function handleMinimize(targetUser) {
    setMinimizedChats(prev => {
      if (prev.find(c => c.key === targetUser.key)) return prev;
      return [...prev, targetUser];
    });
    setActiveChat(null);
  }

  function handleCloseChat(targetUser) {
    setMinimizedChats(prev => prev.filter(c => c.key !== targetUser.key));
    if (activeChat?.key === targetUser.key) {
      setActiveChat(null);
    }
  }

  function handleRestore(targetUser) {
    setMinimizedChats(prev => prev.filter(c => c.key !== targetUser.key));
    setActiveChat(targetUser);
    setUnreadCounts(prev => ({ ...prev, [targetUser.key]: 0 }));
  }

  return (
    <div className="widget" style={{ padding: 0 }}>
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
        <div className="widget-title" style={{ marginBottom: 8 }}>Colaboradores</div>
        <input
          placeholder="Buscar..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: '100%', padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 12, fontFamily: 'inherit', outline: 'none' }}
        />
      </div>
      <div style={{ padding: '10px 14px', maxHeight: 460, overflowY: 'auto' }}>
        {filtered.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>Nenhum encontrado</div>
        ) : (
          filtered.map(u => (
            <UserMiniCard
              key={u.key}
              u={u}
              onChat={handleOpenChat}
              onProfile={target => openColleagueProfile(target.key)}
            />
          ))
        )}
      </div>

      {/* Minimized chats bar */}
      {minimizedChats.length > 0 && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          display: 'flex', gap: 6, padding: '8px 16px',
          background: 'var(--surface)', borderTop: '1px solid var(--border)',
          zIndex: 99999, overflowX: 'auto', justifyContent: 'center',
          boxShadow: '0 -4px 20px rgba(0,0,0,0.15)',
        }}>
          {minimizedChats.map(u => (
            <MinimizedChat
              key={u.key}
              u={u}
              unread={unreadCounts[u.key] || 0}
              onRestore={handleRestore}
              onCloseMinimized={handleCloseChat}
            />
          ))}
        </div>
      )}

      {/* Active chat window */}
      {activeChat && (
        <ChatWindow
          targetUser={activeChat}
          currentUser={user}
          onClose={() => handleCloseChat(activeChat)}
          onMinimize={() => handleMinimize(activeChat)}
        />
      )}
    </div>
  );
}