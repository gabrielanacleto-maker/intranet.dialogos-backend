import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

const MOODS = [
  { key: 'feliz',         label: 'Feliz',          emoji: '😊' },
  { key: 'motivado',      label: 'Motivado',        emoji: '💪' },
  { key: 'inspirado',     label: 'Inspirado',       emoji: '✨' },
  { key: 'sobrecarregado',label: 'Sobrecarregado',  emoji: '🤯' },
  { key: 'doente',        label: 'Doente',          emoji: '🤒' },
  { key: 'triste',        label: 'Triste',          emoji: '😟' },
];

export default function MoodWidget() {
  const { user } = useAuth();
  const [selected, setSelected] = useState(null);
  const [sent, setSent] = useState(false);

  // Verifica se já enviou humor hoje
  useEffect(() => {
    const key = `mood_today_${user?.key}`;
    const saved = localStorage.getItem(key);
    if (saved === new Date().toDateString()) setSent(true);
  }, [user?.key]);

  async function handleMood(mood) {
    if (sent) return;
    setSelected(mood.key);
    try {
      await api.post('/api/mood', { mood: mood.key, intensity: 3, reason: '' });
      localStorage.setItem(`mood_today_${user?.key}`, new Date().toDateString());
      setSent(true);
    } catch (err) {
      console.warn('Erro ao salvar humor:', err);
      setSent(true); // salva localmente mesmo assim
    }
  }

  return (
    <div className="surface-card" style={{ padding: '16px 20px', marginBottom: 16 }}>
      <div style={{
        fontSize: 12, fontWeight: 700, color: 'var(--text-muted)',
        letterSpacing: 1, textTransform: 'uppercase', marginBottom: 12,
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        🐾 Como você está se sentindo hoje?
      </div>

      {sent ? (
        <div style={{ fontSize: 13, color: 'var(--gold)', fontWeight: 600, padding: '8px 0' }}>
          {selected
            ? `${MOODS.find(m => m.key === selected)?.emoji} Humor registrado! Obrigado 💛`
            : '✅ Humor já registrado hoje!'}
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {MOODS.map(mood => (
            <button
              key={mood.key}
              onClick={() => handleMood(mood)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                gap: 4, padding: '10px 14px', borderRadius: 12,
                border: '1.5px solid var(--border)',
                background: selected === mood.key ? 'rgba(201,168,76,0.15)' : 'transparent',
                cursor: 'pointer', transition: 'all 0.15s', minWidth: 72,
              }}
              onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--gold)'}
              onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
            >
              <span style={{ fontSize: 26 }}>{mood.emoji}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}>{mood.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
