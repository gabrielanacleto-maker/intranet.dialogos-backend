import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';

const MOODS = [
  { key: 'happy', emoji: '😊', label: 'Feliz' },
  { key: 'motivated', emoji: '💪', label: 'Motivado' },
  { key: 'inspired', emoji: '✨', label: 'Inspirado' },
  { key: 'overwhelmed', emoji: '😰', label: 'Sobrecarregado' },
  { key: 'sick', emoji: '🤒', label: 'Doente' },
  { key: 'sad', emoji: '😢', label: 'Triste' },
];

export default function MoodWidget() {
  const { user } = useAuth();
  const toast = useToast();
  const [selectedMood, setSelectedMood] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [reason, setReason] = useState('');
  const [intensity, setIntensity] = useState(3);
  const [saving, setSaving] = useState(false);

  async function handleMoodSelect(mood) {
    setSelectedMood(mood);
    setShowModal(true);
    setReason('');
    setIntensity(3);
  }

  async function saveMood() {
    if (!selectedMood) return;
    setSaving(true);
    try {
      await api.saveMood({
        mood: selectedMood.key,
        intensity,
        reason: reason.trim(),
      });
      toast('Humor registrado com sucesso! 💭', 'success');
      setShowModal(false);
      setSelectedMood(null);
      setReason('');
      setIntensity(3);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {/* Widget de Humor */}
      <div style={{
        background: 'linear-gradient(135deg, rgba(201,168,76,0.08) 0%, rgba(201,168,76,0.02) 100%)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '16px',
        marginBottom: '16px'
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          🎭 Como você está se sentindo hoje?
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {MOODS.map(mood => (
            <button
              key={mood.key}
              onClick={() => handleMoodSelect(mood)}
              style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: '12px',
                padding: '12px 16px',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 6,
                fontSize: 24,
                transition: 'all 0.2s',
                flex: '0 0 calc(16.66% - 7px)',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'rgba(201,168,76,0.15)';
                e.currentTarget.style.borderColor = 'var(--gold)';
                e.currentTarget.style.transform = 'scale(1.05)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'var(--surface)';
                e.currentTarget.style.borderColor = 'var(--border)';
                e.currentTarget.style.transform = 'scale(1)';
              }}
            >
              {mood.emoji}
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>
                {mood.label}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Modal de Detalhes */}
      {showModal && (
        <div className="modal-overlay" onClick={() => !saving && setShowModal(false)}>
          <div className="modal-card" style={{ maxWidth: 500 }} onClick={e => e.stopPropagation()}>
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 28, textAlign: 'center', marginBottom: 12 }}>
                {selectedMood?.emoji}
              </div>
              <div style={{ fontSize: 18, fontWeight: 700, textAlign: 'center', color: 'var(--gold)', marginBottom: 4 }}>
                Você está {selectedMood?.label.toLowerCase()}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', textAlign: 'center' }}>
                Conte-nos mais sobre como se sente
              </div>
            </div>

            {/* Campo de Motivo */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 8, textTransform: 'uppercase' }}>
                Qual é o motivo? (opcional)
              </label>
              <textarea
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="Ex: Consegui finalizar um projeto importante..."
                style={{
                  width: '100%',
                  padding: '12px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg)',
                  color: 'var(--text)',
                  fontSize: 13,
                  fontFamily: 'inherit',
                  resize: 'vertical',
                  minHeight: 80,
                  boxSizing: 'border-box'
                }}
              />
            </div>

            {/* Intensidade */}
            <div style={{ marginBottom: 24 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', display: 'block', marginBottom: 12, textTransform: 'uppercase' }}>
                Intensidade: <span style={{ color: 'var(--gold)', fontWeight: 700 }}>{intensity} - {intensity === 1 ? 'Leve' : intensity === 5 ? 'Intenso' : 'Moderado'}</span>
              </label>
              <input
                type="range"
                min="1"
                max="5"
                value={intensity}
                onChange={e => setIntensity(Number(e.target.value))}
                style={{
                  width: '100%',
                  cursor: 'pointer',
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
                <span>Leve</span>
                <span>Moderado</span>
                <span>Intenso</span>
              </div>
            </div>

            {/* Botões */}
            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button
                onClick={() => setShowModal(false)}
                disabled={saving}
                className="btn-admin btn-secondary"
              >
                Cancelar
              </button>
              <button
                onClick={saveMood}
                disabled={saving}
                className="btn-admin btn-primary"
              >
                {saving ? '⏳ Salvando...' : 'Salvar Humor'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
