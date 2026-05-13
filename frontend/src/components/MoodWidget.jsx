import { useState } from 'react';
import { api } from '../services/api';

const MOODS = [
  { key: 'feliz', label: 'Feliz', emoji: '\u{1F60A}' },
  { key: 'motivado', label: 'Motivado', emoji: '\u{1F4AA}' },
  { key: 'inspirado', label: 'Inspirado', emoji: '\u2728' },
  { key: 'sobrecarregado', label: 'Sobrecarregado', emoji: '\u{1F92F}' },
  { key: 'doente', label: 'Doente', emoji: '\u{1F912}' },
  { key: 'triste', label: 'Triste', emoji: '\u{1F61F}' },
];

const INTENSITIES = [
  { value: 1, label: 'Levíssimo' },
  { value: 2, label: 'Leve' },
  { value: 3, label: 'Moderado' },
  { value: 4, label: 'Alta' },
  { value: 5, label: 'Intensa' },
];

export default function MoodWidget() {
  const [selected, setSelected] = useState(null);
  const [intensity, setIntensity] = useState(null);
  const [reason, setReason] = useState('');
  const [sending, setSending] = useState(false);

  async function handleConfirm() {
    if (!selected || !intensity) return;
    setSending(true);
    try {
      await api.saveMood({ mood: selected.key, intensity, reason: reason.trim() });
      setSelected(null); setIntensity(null); setReason('');
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="surface-card" style={{ padding: 24, marginBottom: 20, borderRadius: 16 }}>
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 3, textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 4 }}>Bem-estar</div>
        <h2 style={{ fontFamily: 'Playfair Display', fontSize: 26, margin: 0, fontWeight: 600 }}>Termômetro do Humor</h2>
        <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>Como você está se sentindo agora?</p>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center', marginBottom: selected ? 16 : 0 }}>
        {MOODS.map(mood => (
          <button key={mood.key} onClick={() => { setSelected(mood); setIntensity(null); setReason(''); }} style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
            padding: '10px 12px', borderRadius: 12, minWidth: 76,
            border: `1.5px solid ${selected?.key === mood.key ? 'var(--gold)' : 'var(--border)'}`,
            background: selected?.key === mood.key ? 'rgba(201,168,76,0.12)' : 'var(--surface)',
            cursor: 'pointer', transition: 'all 0.2s',
            boxShadow: selected?.key === mood.key ? '0 4px 16px rgba(201,168,76,0.15)' : 'none',
          }}>
            <span style={{ fontSize: 28, lineHeight: 1.2, display: 'block' }}>{mood.emoji}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: 0.3 }}>{mood.label}</span>
          </button>
        ))}
      </div>
      {selected && (
        <div style={{ marginTop: 4 }}>
          <div style={{ padding: 16, borderRadius: 12, background: 'var(--bg)', border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, letterSpacing: 0.5 }}>
              {selected.emoji} Qual a intensidade?
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
              {INTENSITIES.map(i => (
                <button key={i.value} onClick={() => setIntensity(i.value)} style={{
                  padding: '5px 12px', borderRadius: 8, fontSize: 12, fontWeight: 600,
                  border: `1.5px solid ${intensity === i.value ? 'var(--gold)' : 'var(--border)'}`,
                  background: intensity === i.value ? 'var(--gold)' : 'transparent',
                  color: intensity === i.value ? '#000' : 'var(--text-muted)',
                  cursor: 'pointer', transition: 'all 0.15s',
                  fontFamily: 'inherit',
                }}>{i.label}</button>
              ))}
            </div>
            <textarea
              value={reason} onChange={e => setReason(e.target.value.slice(0, 6000))}
              placeholder="Como você está se sentindo? O que aconteceu?"
              rows={3}
              style={{
                width: '100%', padding: 10, borderRadius: 8,
                border: '1.5px solid var(--border)', background: 'var(--surface)',
                color: 'var(--text)', fontFamily: 'inherit', fontSize: 13,
                resize: 'vertical', boxSizing: 'border-box', lineHeight: 1.5,
              }}
            />
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              marginTop: 8,
            }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{reason.length}/6000</span>
              <button
                onClick={handleConfirm}
                disabled={!intensity || sending}
                style={{
                  padding: '8px 20px', borderRadius: 8, fontWeight: 700, fontSize: 13,
                  background: intensity ? 'var(--gold)' : 'var(--border)',
                  color: intensity ? '#000' : 'var(--text-muted)',
                  border: 'none', cursor: intensity ? 'pointer' : 'not-allowed',
                  transition: 'all 0.15s', fontFamily: 'inherit',
                  opacity: sending ? 0.6 : 1,
                }}
              >
                {sending ? 'Registrando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
