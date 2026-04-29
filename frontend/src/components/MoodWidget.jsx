import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';

const MOODS = [
  { key: 'feliz',          label: 'Feliz',          emoji: '😊' },
  { key: 'motivado',       label: 'Motivado',        emoji: '💪' },
  { key: 'inspirado',      label: 'Inspirado',       emoji: '✨' },
  { key: 'sobrecarregado', label: 'Sobrecarregado',  emoji: '🤯' },
  { key: 'doente',         label: 'Doente',          emoji: '🤒' },
  { key: 'triste',         label: 'Triste',          emoji: '😟' },
];

const INTENSITIES = [
  { value: 1, label: 'Levíssimo' },
  { value: 2, label: 'Leve' },
  { value: 3, label: 'Moderado' },
  { value: 4, label: 'Alta' },
  { value: 5, label: 'Intensa' },
];

export default function MoodWidget() {
  const { user } = useAuth();
  const [selected, setSelected] = useState(null);
  const [intensity, setIntensity] = useState(null);
  const [reason, setReason] = useState('');
  const [sending, setSending] = useState(false);


  async function handleConfirm() {
    if (!selected || !intensity) return;
    setSending(true);
    try {
      const token = localStorage.getItem('dialogos_token');
      await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/mood`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ mood: selected.key, intensity, reason: reason.trim() }),
      });

      setSelected(null);
setIntensity(null);
setReason('');

    } catch (err) {
      console.warn('Erro ao salvar humor:', err);
      setSelected(null);
setIntensity(null);
setReason('');

    } finally {
      setSending(false);
    }
  }


  return (
    <div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: selected ? 14 : 0 }}>
        {MOODS.map(mood => (
          <button
            key={mood.key}
            onClick={() => { setSelected(mood); setIntensity(null); setReason(''); }}
            style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              gap: 4, padding: '8px 10px', borderRadius: 12,
              border: `1.5px solid ${selected?.key === mood.key ? 'var(--gold)' : 'var(--border)'}`,
              background: selected?.key === mood.key ? 'rgba(201,168,76,0.15)' : 'transparent',
              cursor: 'pointer', transition: 'all 0.15s', minWidth: 64,
            }}
          >
            <span style={{ fontSize: 24 }}>{mood.emoji}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 500 }}>{mood.label}</span>
          </button>
        ))}
      </div>

      {selected && (
        <div style={{ marginTop: 12, padding: '14px 16px', borderRadius: 12, background: 'rgba(201,168,76,0.06)', border: '1px solid rgba(201,168,76,0.2)' }}>
          {/* Intensidade */}
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            {selected.emoji} Qual a intensidade?
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
            {INTENSITIES.map(i => (
              <button
                key={i.value}
                onClick={() => setIntensity(i.value)}
                style={{
                  padding: '6px 12px', borderRadius: 20, fontSize: 12, fontWeight: 600,
                  border: `1.5px solid ${intensity === i.value ? 'var(--gold)' : 'var(--border)'}`,
                  background: intensity === i.value ? 'var(--gold)' : 'transparent',
                  color: intensity === i.value ? '#000' : 'var(--text-muted)',
                  cursor: 'pointer', transition: 'all 0.15s',
                }}
              >
                {i.value} — {i.label}
              </button>
            ))}
          </div>

          {/* Motivo */}
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            📝 Descreva o motivo <span style={{ fontWeight: 400, textTransform: 'none' }}>(opcional)</span>
          </div>
          <textarea
            value={reason}
            onChange={e => setReason(e.target.value.slice(0, 6000))}
            placeholder="Como você está se sentindo? O que aconteceu?"
            rows={3}
            style={{
              width: '100%', padding: '10px 12px', borderRadius: 8,
              border: '1.5px solid var(--border)', background: 'var(--bg)',
              color: 'var(--text)', fontFamily: 'inherit', fontSize: 13,
              resize: 'vertical', boxSizing: 'border-box', marginBottom: 4,
            }}
          />
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'right', marginBottom: 12 }}>
            {reason.length}/6000
          </div>

          <button
            onClick={handleConfirm}
            disabled={!intensity || sending}
            style={{
              padding: '8px 20px', borderRadius: 8, fontWeight: 700, fontSize: 13,
              background: intensity ? 'var(--gold)' : 'var(--border)',
              color: intensity ? '#000' : 'var(--text-muted)',
              border: 'none', cursor: intensity ? 'pointer' : 'not-allowed',
              transition: 'all 0.2s',
            }}
          >
            {sending ? 'Registrando...' : '✅ Confirmar'}
          </button>
        </div>
      )}
    </div>
  );
}