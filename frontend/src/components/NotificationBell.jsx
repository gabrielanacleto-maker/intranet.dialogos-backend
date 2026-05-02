import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../services/api';

// ── Icon map por tipo ────────────────────────────────────────────────────────
const TYPE_ICON = {
  post:       '📋',
  comunicado: '📢',
  comment:    '💬',
  mention:    '👋',
  feedback:   '⭐',
  xp:         '💰',
  system:     '🏆',
  default:    '🔔',
};

// ── Anti-spam: max 1 som a cada 2s ──────────────────────────────────────────
let _lastPlayed = 0;

function playNotifSound() {
  const soundEnabled = localStorage.getItem('dialogos_notif_sound') !== 'false';
  if (!soundEnabled) return;
  const now = Date.now();
  if (now - _lastPlayed < 2000) return;
  _lastPlayed = now;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Gera tom suave tipo Slack — dois osciladores curtos
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0.18, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);

    const osc1 = ctx.createOscillator();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(880, ctx.currentTime);
    osc1.frequency.exponentialRampToValueAtTime(1100, ctx.currentTime + 0.15);
    osc1.connect(gain);
    osc1.start(ctx.currentTime);
    osc1.stop(ctx.currentTime + 0.5);
  } catch (_) {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function timeAgo(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))) / 1000;
  if (diff < 60)    return 'agora mesmo';
  if (diff < 3600)  return `${Math.floor(diff / 60)}min atrás`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h atrás`;
  return `${Math.floor(diff / 86400)}d atrás`;
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function NotificationBell() {
  const [open, setOpen]           = useState(false);
  const [notifs, setNotifs]       = useState([]);
  const [unread, setUnread]       = useState(0);
  const [loading, setLoading]     = useState(false);
  const [soundOn, setSoundOn]     = useState(
    () => localStorage.getItem('dialogos_notif_sound') !== 'false'
  );
  const prevUnread = useRef(0);
  const panelRef   = useRef(null);
  const pollRef    = useRef(null);

  // Fetch unread count (lightweight, polling)
  const fetchCount = useCallback(async () => {
    try {
      const data = await api.getUnreadCount();
      const count = data.count || 0;
      if (count > prevUnread.current) playNotifSound();
      prevUnread.current = count;
      setUnread(count);
    } catch (_) {}
  }, []);

  // Fetch full list (only when panel opens)
  const fetchNotifs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getNotifications();
      setNotifs(data);
      setUnread(data.filter(n => !n.is_read).length);
    } catch (_) {}
    finally { setLoading(false); }
  }, []);

  // Poll every 30s for unread count
  useEffect(() => {
    fetchCount();
    pollRef.current = setInterval(fetchCount, 30000);
    return () => clearInterval(pollRef.current);
  }, [fetchCount]);

  // Open/close panel
  useEffect(() => {
    if (open) fetchNotifs();
  }, [open, fetchNotifs]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handle(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open]);

  async function handleMarkRead(id, e) {
    e.stopPropagation();
    try {
      await api.markNotifRead(id);
      setNotifs(ns => ns.map(n => n.id === id ? { ...n, is_read: true } : n));
      setUnread(u => Math.max(0, u - 1));
    } catch (_) {}
  }

  async function handleMarkAll() {
    try {
      await api.markAllNotifRead();
      setNotifs(ns => ns.map(n => ({ ...n, is_read: true })));
      setUnread(0);
    } catch (_) {}
  }

  function toggleSound() {
    const next = !soundOn;
    setSoundOn(next);
    localStorage.setItem('dialogos_notif_sound', next ? 'true' : 'false');
  }

  return (
    <div ref={panelRef} style={{ position: 'relative' }}>
      {/* ── Bell button ── */}
      <div
        className="topbar-icon"
        title="Notificações"
        onClick={() => setOpen(o => !o)}
        style={{ position: 'relative' }}
      >
        🔔
        {unread > 0 && (
          <span style={{
            position: 'absolute', top: -4, right: -4,
            minWidth: 16, height: 16, borderRadius: 8,
            background: '#ef4444', color: '#fff',
            fontSize: 10, fontWeight: 700,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '0 3px', lineHeight: 1,
            border: '2px solid var(--bg)',
            animation: 'pulse 1.5s infinite',
          }}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </div>

      {/* ── Dropdown panel ── */}
      {open && (
        <div style={{
          position: 'absolute', top: 40, right: 0,
          width: 360, maxHeight: 520,
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          zIndex: 9999,
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}>
          {/* Header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '14px 16px 10px',
            borderBottom: '1px solid var(--border)',
            flexShrink: 0,
          }}>
            <div style={{ fontFamily: 'Playfair Display', fontSize: 15, fontWeight: 600 }}>
              🔔 Notificações {unread > 0 && <span style={{ color: '#ef4444', fontSize: 12 }}>({unread})</span>}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button onClick={toggleSound} title={soundOn ? 'Som ativado' : 'Som desativado'} style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 14, color: soundOn ? 'var(--gold)' : 'var(--text-muted)',
                padding: '2px 4px',
              }}>{soundOn ? '🔊' : '🔇'}</button>
              {unread > 0 && (
                <button onClick={handleMarkAll} style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'transparent',
                  color: 'var(--gold)', cursor: 'pointer', fontWeight: 600,
                }}>Marcar todas</button>
              )}
            </div>
          </div>

          {/* List */}
          <div style={{ overflowY: 'auto', flex: 1 }}>
            {loading && (
              <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)', fontSize: 13 }}>
                Carregando...
              </div>
            )}
            {!loading && notifs.length === 0 && (
              <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>🔕</div>
                <div style={{ fontSize: 13 }}>Nenhuma notificação</div>
              </div>
            )}
            {notifs.map(n => (
              <div key={n.id} style={{
                display: 'flex', gap: 12, padding: '12px 16px',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                background: n.is_read ? 'transparent' : 'rgba(201,168,76,0.06)',
                transition: 'background 0.2s',
                cursor: 'default',
              }}>
                {/* Icon */}
                <div style={{
                  width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
                  background: 'rgba(255,255,255,0.06)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 16,
                }}>
                  {TYPE_ICON[n.type] || TYPE_ICON.default}
                </div>

                {/* Content */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: n.is_read ? 500 : 700, marginBottom: 2, color: 'var(--text)' }}>
                    {n.title}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.4, wordBreak: 'break-word' }}>
                    {n.message}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, opacity: 0.6 }}>
                    {timeAgo(n.created_at)}
                  </div>
                </div>

                {/* Unread dot + mark read */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                  {!n.is_read && (
                    <>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#ef4444' }} />
                      <button
                        onClick={e => handleMarkRead(n.id, e)}
                        title="Marcar como lida"
                        style={{
                          background: 'none', border: 'none', cursor: 'pointer',
                          fontSize: 10, color: 'var(--text-muted)', padding: 0,
                          lineHeight: 1,
                        }}
                      >✓</button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
