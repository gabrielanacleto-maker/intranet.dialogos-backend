import { useState, useEffect } from 'react';

import { useAuth } from '../context/AuthContext'; // <-- se já não tiver


const MOODS = [
  { key: 'feliz',          label: 'Feliz',           emoji: '😊', color: '#22c55e' },
  { key: 'motivado',       label: 'Motivado',         emoji: '💪', color: '#f59e0b' },
  { key: 'inspirado',      label: 'Inspirado',        emoji: '✨', color: '#a855f7' },
  { key: 'sobrecarregado', label: 'Sobrecarregado',   emoji: '🤯', color: '#ef4444' },
  { key: 'doente',         label: 'Doente',           emoji: '🤒', color: '#64748b' },
  { key: 'triste',         label: 'Triste',           emoji: '😟', color: '#3b82f6' },
];

const INTENSITY_LABEL = { 1: 'Levíssimo', 2: 'Leve', 3: 'Moderado', 4: 'Alta', 5: 'Intensa' };

function getMoodInfo(key) {
  return MOODS.find(m => m.key === key) || { key, label: key, emoji: '❓', color: '#888' };
}

function getMonthLabel(dateStr) {
  const d = new Date(dateStr + '-01');
  return d.toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });
}

export default function MoodReport() {

  const { user } = useAuth();

  const canReset = true;


  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedMonth, setSelectedMonth] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('dialogos_token');
    fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/mood/history`, {
      headers: { Authorization: `Bearer ${token}` }
    })
      .then(r => r.json())
      .then(data => {
        setHistory(Array.isArray(data) ? data : []);
        const now = new Date();
        setSelectedMonth(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`);
      })
      .catch(() => setHistory([]))
      .finally(() => setLoading(false));
  }, []);

  const byMonth = {};
  history.forEach(entry => {
    const month = entry.created_at?.slice(0, 7);
    if (!month) return;
    if (!byMonth[month]) byMonth[month] = [];
    byMonth[month].push(entry);
  });

  const months = Object.keys(byMonth).sort((a, b) => b.localeCompare(a));
  const currentEntries = byMonth[selectedMonth] || [];

  const counts = {};
  currentEntries.forEach(e => { counts[e.mood] = (counts[e.mood] || 0) + 1; });
  const total = currentEntries.length;

  const topMood = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  const topMoodInfo = topMood ? getMoodInfo(topMood[0]) : null;

  function downloadReport() {
    const monthLabel = selectedMonth ? getMonthLabel(selectedMonth) : 'Relatório';
    const lines = [
      `RELATÓRIO DE HUMOR — ${monthLabel.toUpperCase()}`,
      `Gerado em: ${new Date().toLocaleDateString('pt-BR')}`,
      `Total de registros: ${total}`,
      topMoodInfo ? `Humor dominante: ${topMoodInfo.emoji} ${topMoodInfo.label}` : '',
      '',
      '─'.repeat(50),
      '',
      ...MOODS.map(mood => {
        const count = counts[mood.key] || 0;
        if (!count) return null;
        const pct = Math.round((count / total) * 100);
        return `${mood.emoji} ${mood.label}: ${count}x (${pct}%)`;
      }).filter(Boolean),
      '',
      '─'.repeat(50),
      'REGISTROS DETALHADOS',
      '',
      ...[...currentEntries].reverse().map(entry => {
        const info = getMoodInfo(entry.mood);
        const date = new Date(entry.created_at).toLocaleDateString('pt-BR');
        const intensity = entry.intensity ? `Intensidade: ${entry.intensity} — ${INTENSITY_LABEL[entry.intensity]}` : '';
        const reason = entry.reason ? `Motivo: ${entry.reason}` : '';
        return [
          `[${date}] ${info.emoji} ${info.label}`,
          intensity,
          reason,
          '',
        ].filter(Boolean).join('\n');
      }),
    ].join('\n');

    const blob = new Blob([lines], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `relatorio-humor-${selectedMonth}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }
async function handleReset() {
  const confirm = window.confirm("Tem certeza que deseja resetar seus dados?");
  if (!confirm) return;

  try {
    const token = localStorage.getItem('dialogos_token');

    await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/mood/reset`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        user_id: user.id
      }),
    });

    alert('Seus dados foram resetados');
    window.location.reload();

  } catch (err) {
    console.error(err);
    alert('Erro ao resetar');
  }
}


  return (
    <div className="surface-card" style={{ padding: 20, marginTop: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600 }}>
          📊 Relatório de Humor
        </div>
        {total > 0 && (
  <div style={{ display: 'flex', gap: 8 }}>
    
    <button onClick={downloadReport} style={{
      padding: '6px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600,
      background: 'transparent', border: '1.5px solid var(--gold)',
      color: 'var(--gold)', cursor: 'pointer',
    }}>
      ⬇️ Baixar
    </button>

    {canReset && (
      <button
        onClick={handleReset}
        style={{
          padding: '6px 14px',
          borderRadius: 8,
          fontSize: 12,
          fontWeight: 600,
          background: '#ff4d4f',
          color: '#fff',
          border: 'none',
          cursor: 'pointer'
        }}
      >
        🗑️ Resetar
      </button>
    )}

  </div>
)}

      </div>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
        Acompanhe como você tem se sentido ao longo do mês.
      </p>

      {months.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <select value={selectedMonth} onChange={e => setSelectedMonth(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit', fontSize: 13 }}>
            {months.map(m => <option key={m} value={m}>{getMonthLabel(m)}</option>)}
          </select>
        </div>
      )}

      {total === 0 ? (
        <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>📭</div>
          <p style={{ fontSize: 13 }}>Nenhum humor registrado neste mês.</p>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 120, background: 'rgba(201,168,76,0.08)', borderRadius: 12, padding: '14px 16px', border: '1px solid rgba(201,168,76,0.2)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Registros</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--gold)' }}>{total}</div>
            </div>
            {topMoodInfo && (
              <div style={{ flex: 1, minWidth: 120, background: `${topMoodInfo.color}15`, borderRadius: 12, padding: '14px 16px', border: `1px solid ${topMoodInfo.color}40` }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Humor Dominante</div>
                <div style={{ fontSize: 20 }}>{topMoodInfo.emoji} <span style={{ fontSize: 14, fontWeight: 700, color: topMoodInfo.color }}>{topMoodInfo.label}</span></div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
            {MOODS.map(mood => {
              const count = counts[mood.key] || 0;
              if (!count) return null;
              const pct = Math.round((count / total) * 100);
              return (
                <div key={mood.key}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, alignItems: 'center' }}>
                    <span style={{ fontSize: 13 }}>{mood.emoji} {mood.label}</span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>{count}x · {pct}%</span>
                  </div>
                  <div style={{ height: 8, borderRadius: 8, background: 'var(--border)', overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${pct}%`, borderRadius: 8, background: mood.color, transition: 'width 0.6s ease' }} />
                  </div>
                </div>
              );
            })}
          </div>

          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>
              Últimos registros
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[...currentEntries].reverse().slice(0, 8).map((entry, i) => {
                const info = getMoodInfo(entry.mood);
                const date = new Date(entry.created_at);
                return (
                  <div key={i} style={{ padding: '10px 14px', borderRadius: 10, background: 'var(--bg)', border: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: entry.reason ? 6 : 0 }}>
                      <span style={{ fontSize: 20 }}>{info.emoji}</span>
                      <div style={{ flex: 1 }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: info.color }}>{info.label}</span>
                        {entry.intensity && (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>
                            · {INTENSITY_LABEL[entry.intensity]}
                          </span>
                        )}
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}
                      </span>
                    </div>
                    {entry.reason && (
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', paddingLeft: 30, lineHeight: 1.5 }}>
                        {entry.reason}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
