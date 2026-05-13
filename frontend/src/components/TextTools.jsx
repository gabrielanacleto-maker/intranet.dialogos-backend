import { useMemo, useState } from 'react';
import { api } from '../services/api';

export function renderTextMedia(text) {
  const parts = String(text || '').split(/(https?:\/\/[^\s]+)/g);
  return parts.map((part, i) => {
    if (!/^https?:\/\//i.test(part)) return <span key={i}>{part}</span>;
    if (/media\d?\.giphy\.com|\.gif(\?|$)/i.test(part)) {
      return <img key={i} src={part} alt="GIF" style={{ display: 'block', maxWidth: 260, width: '100%', borderRadius: 8, margin: '8px 0' }} />;
    }
    return <a key={i} href={part} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--gold)' }}>{part}</a>;
  });
}

export function GifPicker({ onSelect }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [gifs, setGifs] = useState([]);
  async function search() {
    if (!q.trim()) return;
    const data = await api.searchGifs(q.trim());
    setGifs(data.gifs || []);
  }
  return (
    <span style={{ position: 'relative' }}>
      <button type="button" className="btn-admin btn-secondary" style={{ padding: '6px 10px', fontSize: 12 }} onClick={() => setOpen(v => !v)}>GIF</button>
      {open && (
        <div style={{ position: 'absolute', zIndex: 200, right: 0, top: 36, width: 320, padding: 12, borderRadius: 12, background: 'var(--surface)', border: '1px solid var(--border)', boxShadow: '0 8px 32px rgba(0,0,0,.35)' }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()} placeholder="Buscar GIF..." style={{ flex: 1, padding: 8, borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }} />
            <button type="button" className="btn-admin btn-primary" onClick={search}>Buscar</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, maxHeight: 260, overflowY: 'auto' }}>
            {gifs.map(g => <button key={g.id} type="button" onClick={() => { onSelect(g.url); setOpen(false); }} style={{ border: 0, padding: 0, background: 'none', cursor: 'pointer' }}><img src={g.url} alt={g.title} style={{ width: '100%', height: 82, objectFit: 'cover', borderRadius: 6 }} /></button>)}
          </div>
        </div>
      )}
    </span>
  );
}

export function MentionSuggest({ value, onChange, users = [], inputRef }) {
  const match = value.match(/@([A-Za-zÀ-ÿ0-9_.-]*)$/);
  const items = useMemo(() => {
    const q = (match?.[1] || '').toLowerCase();
    if (!match) return [];
    return users.filter(u => [u.name, u.key].join(' ').toLowerCase().includes(q)).slice(0, 6);
  }, [match, users]);
  if (!items.length) return null;
  return (
    <div style={{ position: 'absolute', zIndex: 150, left: 0, bottom: '100%', minWidth: 260, maxHeight: 240, overflowY: 'auto', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, boxShadow: '0 8px 28px rgba(0,0,0,.3)' }}>
      {items.map(u => (
        <button key={u.key} type="button" onClick={() => { onChange(value.replace(/@([A-Za-zÀ-ÿ0-9_.-]*)$/, `@${u.key} `)); inputRef?.current?.focus(); }} style={{ width: '100%', display: 'flex', gap: 8, alignItems: 'center', padding: 9, background: 'none', border: 0, color: 'var(--text)', cursor: 'pointer', textAlign: 'left' }}>
          <span style={{ width: 28, height: 28, borderRadius: '50%', background: 'var(--gold)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, flexShrink: 0 }}>{u.initials}</span>
          <span><strong style={{ display: 'block', fontSize: 13 }}>{u.name}</strong><small style={{ color: 'var(--text-muted)' }}>{u.role}</small></span>
        </button>
      ))}
    </div>
  );
}
