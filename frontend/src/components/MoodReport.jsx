import { useEffect, useState } from 'react';
import { jsPDF } from 'jspdf';
import { api } from '../services/api';

const MOODS = [
  { key: 'feliz', label: 'Feliz', emoji: '\u{1F60A}', color: '#22c55e' },
  { key: 'motivado', label: 'Motivado', emoji: '\u{1F4AA}', color: '#f59e0b' },
  { key: 'inspirado', label: 'Inspirado', emoji: '\u2728', color: '#a855f7' },
  { key: 'sobrecarregado', label: 'Sobrecarregado', emoji: '\u{1F92F}', color: '#ef4444' },
  { key: 'doente', label: 'Doente', emoji: '\u{1F912}', color: '#64748b' },
  { key: 'triste', label: 'Triste', emoji: '\u{1F61F}', color: '#3b82f6' },
];

const INTENSITY_LABEL = { 1: 'Levíssimo', 2: 'Leve', 3: 'Moderado', 4: 'Alta', 5: 'Intensa' };
const info = key => MOODS.find(m => m.key === key) || { key, label: key, emoji: '?', color: '#888' };
const monthLabel = m => new Date(`${m}-01`).toLocaleDateString('pt-BR', { month: 'long', year: 'numeric' });

export default function MoodReport() {
  const [history, setHistory] = useState([]);
  const [selectedMonth, setSelectedMonth] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getMoodHistory().then(data => {
      setHistory(Array.isArray(data) ? data : []);
      const now = new Date();
      setSelectedMonth(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`);
    }).catch(() => setHistory([])).finally(() => setLoading(false));
  }, []);

  const byMonth = {};
  history.forEach(e => {
    const m = e.created_at?.slice(0, 7);
    if (m) (byMonth[m] ||= []).push(e);
  });
  const months = Object.keys(byMonth).sort((a, b) => b.localeCompare(a));
  const entries = byMonth[selectedMonth] || [];
  const total = entries.length;
  const counts = {};
  entries.forEach(e => { counts[e.mood] = (counts[e.mood] || 0) + 1; });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  const topInfo = top ? info(top[0]) : null;

  async function downloadReport() {
    const doc = new jsPDF();
    const pageW = doc.internal.pageSize.getWidth();
    let y = 20;

    doc.setFontSize(18);
    doc.text('Relatorio de Humor', pageW / 2, y, { align: 'center' });
    y += 10;

    doc.setFontSize(10);
    doc.text(`Periodo: ${monthLabel(selectedMonth)}`, 14, y);
    y += 8;
    doc.text(`Total de registros: ${total}`, 14, y);
    y += 12;

    if (topInfo) {
      doc.setFontSize(12);
      doc.text(`Humor dominante: ${topInfo.label} (${top[1]}x)`, 14, y);
      y += 10;
    }

    MOODS.forEach(m => {
      const count = counts[m.key] || 0;
      if (!count) return;
      const pct = Math.round((count / total) * 100);
      doc.setFontSize(11);
      doc.text(`${m.label}: ${count}x (${pct}%)`, 20, y);
      y += 7;
    });

    y += 6;
    doc.setFontSize(14);
    doc.text('Registros individuais', 14, y);
    y += 8;

    doc.setFontSize(9);
    const dayEntries = [...entries].reverse();
    for (const e of dayEntries) {
      const m = info(e.mood);
      const date = e.created_at ? new Date(e.created_at).toLocaleDateString('pt-BR') : '';
      const intensity = e.intensity ? ` - ${INTENSITY_LABEL[e.intensity] || e.intensity}` : '';
      const line = `${date} - ${m.label}${intensity}${e.reason ? ': ' + e.reason : ''}`;
      if (y > 275) { doc.addPage(); y = 20; }
      doc.text(line, 14, y);
      y += 6;
    }

    doc.save(`relatorio-humor-${selectedMonth || 'atual'}.pdf`);
  }

  async function handleReset() {
    if (!window.confirm('Tem certeza que deseja resetar seus dados?')) return;
    const token = localStorage.getItem('dialogos_token');
    await fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/mood/reset`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
    window.location.reload();
  }

  return (
    <div className="surface-card" style={{ padding: 20, marginTop: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600 }}>Relatório de Humor</div>
        {total > 0 && <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={downloadReport} className="btn-admin btn-secondary">Baixar PDF</button>
          <button onClick={handleReset} className="btn-admin btn-danger">Resetar</button>
        </div>}
      </div>
      <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>Acompanhe como você tem se sentido ao longo do mês.</p>
      {months.length > 0 && <select value={selectedMonth} onChange={e => setSelectedMonth(e.target.value)} style={{ padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', marginBottom: 16 }}>{months.map(m => <option key={m} value={m}>{monthLabel(m)}</option>)}</select>}
      {loading || total === 0 ? <div style={{ textAlign: 'center', padding: 24, color: 'var(--text-muted)' }}>{loading ? 'Carregando...' : 'Nenhum humor registrado neste mês.'}</div> : <>
        <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 120, background: 'rgba(201,168,76,0.08)', borderRadius: 12, padding: 14, border: '1px solid rgba(201,168,76,0.2)' }}><small>Registros</small><div style={{ fontSize: 24, fontWeight: 800, color: 'var(--gold)' }}>{total}</div></div>
          {topInfo && <div style={{ flex: 1, minWidth: 120, background: `${topInfo.color}15`, borderRadius: 12, padding: 14, border: `1px solid ${topInfo.color}40` }}><small>Humor dominante</small><div style={{ fontSize: 20 }}>{topInfo.emoji} <b style={{ color: topInfo.color }}>{topInfo.label}</b></div></div>}
        </div>
        {MOODS.map(m => {
          const count = counts[m.key] || 0;
          if (!count) return null;
          const pct = Math.round((count / total) * 100);
          return <div key={m.key} style={{ marginBottom: 10 }}><div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}><span>{m.emoji} {m.label}</span><span>{count}x · {pct}%</span></div><div style={{ height: 8, borderRadius: 8, background: 'var(--border)', overflow: 'hidden' }}><div style={{ height: '100%', width: `${pct}%`, background: m.color }} /></div></div>;
        })}
        {[...entries].reverse().slice(0, 8).map((e, i) => {
          const m = info(e.mood);
          return <div key={i} style={{ padding: 10, borderRadius: 10, background: 'var(--bg)', border: '1px solid var(--border)', marginTop: 8, fontSize: 13 }}>{m.emoji} <b style={{ color: m.color }}>{m.label}</b> {e.intensity ? `· ${INTENSITY_LABEL[e.intensity]}` : ''}{e.reason ? <div style={{ color: 'var(--text-muted)', marginTop: 4 }}>{e.reason}</div> : null}</div>;
        })}
      </>}
    </div>
  );
}
