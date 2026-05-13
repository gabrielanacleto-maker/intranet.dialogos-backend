import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';

// ── Constantes ───────────────────────────────────────────────────────────────
const MONTHS = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
const WEEKDAYS = ['Dom','Seg','Ter','Qua','Qui','Sex','Sáb'];
const WEEKDAYS_FULL = ['Domingo','Segunda','Terça','Quarta','Quinta','Sexta','Sábado'];

const EVENT_COLORS = [
  { label: 'Dourado',   value: '#C9A84C' },
  { label: 'Azul',      value: '#378ADD' },
  { label: 'Verde',     value: '#22c55e' },
  { label: 'Rosa',      value: '#ec4899' },
  { label: 'Roxo',      value: '#a855f7' },
  { label: 'Laranja',   value: '#f97316' },
  { label: 'Vermelho',  value: '#ef4444' },
  { label: 'Ciano',     value: '#06b6d4' },
];

const REPEAT_OPTIONS = [
  { value: 'none',    label: 'Não repetir' },
  { value: 'daily',   label: 'Todo dia' },
  { value: 'weekly',  label: 'Toda semana' },
  { value: 'monthly', label: 'Todo mês' },
  { value: 'yearly',  label: 'Todo ano' },
];

function pad(n) { return String(n).padStart(2, '0'); }
function toDateStr(d) { return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`; }
function toTimeStr(d) { return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
function fmtTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtDate(isoStr) {
  if (!isoStr) return '';
  const [y, m, day] = isoStr.split('T')[0].split('-');
  return `${day}/${m}/${y}`;
}
function isSameDay(a, b) {
  return a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate();
}
function eventOnDay(ev, day) {
  const start = new Date(ev.start_date);
  const end = new Date(ev.end_date);
  const d = new Date(day); d.setHours(12);
  return d >= new Date(start.toDateString()) && d <= new Date(end.toDateString());
}

// ── Modal de evento ──────────────────────────────────────────────────────────
function EventModal({ initial, defaultDate, onClose, onSave, onDelete, currentUserKey }) {
  const isOwn = !initial || initial.user_key === currentUserKey;
  const now = new Date();
  const defDate = defaultDate || toDateStr(now);
  const defTime = toTimeStr(now);

  const [form, setForm] = useState({
    title: '', description: '', location: '',
    color: '#C9A84C', is_public: false, all_day: false,
    repeat_type: 'none',
    start_date: `${defDate}T${defTime}`,
    end_date: `${defDate}T${pad(now.getHours()+1)}:${pad(now.getMinutes())}`,
    ...(initial ? {
      ...initial,
      start_date: initial.start_date,
      end_date: initial.end_date,
    } : {}),
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const startDatePart = form.start_date?.split('T')[0] || defDate;
  const startTimePart = form.start_date?.split('T')[1]?.slice(0,5) || defTime;
  const endDatePart = form.end_date?.split('T')[0] || defDate;
  const endTimePart = form.end_date?.split('T')[1]?.slice(0,5) || defTime;

  async function save() {
    if (!form.title.trim()) return alert('Título obrigatório.');
    setSaving(true);
    try { await onSave(form); }
    catch (e) { alert(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 500 }}>
        <div className="modal-header" style={{ borderBottom: `3px solid ${form.color}` }}>
          <h3>{initial ? '✏️ Editar Evento' : '✨ Novo Evento'}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* Título */}
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Título *</label>
            <input value={form.title} onChange={e => set('title', e.target.value)}
              placeholder="Reunião, consulta, lembrete..." autoFocus disabled={!isOwn} />
          </div>

          {/* Cor */}
          <div>
            <label style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-muted)', display: 'block', marginBottom: 8 }}>Cor</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {EVENT_COLORS.map(c => (
                <div key={c.value} onClick={() => isOwn && set('color', c.value)}
                  title={c.label}
                  style={{
                    width: 28, height: 28, borderRadius: '50%', background: c.value,
                    cursor: isOwn ? 'pointer' : 'default',
                    border: form.color === c.value ? '3px solid #fff' : '3px solid transparent',
                    boxShadow: form.color === c.value ? `0 0 0 2px ${c.value}` : 'none',
                    transition: 'all 0.15s',
                  }} />
              ))}
            </div>
          </div>

          {/* Dia inteiro */}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: isOwn ? 'pointer' : 'default', fontSize: 13 }}>
            <input type="checkbox" checked={!!form.all_day} onChange={e => isOwn && set('all_day', e.target.checked)} />
            Dia inteiro
          </label>

          {/* Datas */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Início</label>
              <input type="date" value={startDatePart} disabled={!isOwn}
                onChange={e => set('start_date', `${e.target.value}T${startTimePart}`)} />
              {!form.all_day && (
                <input type="time" value={startTimePart} disabled={!isOwn} style={{ marginTop: 6 }}
                  onChange={e => set('start_date', `${startDatePart}T${e.target.value}`)} />
              )}
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>Fim</label>
              <input type="date" value={endDatePart} disabled={!isOwn}
                onChange={e => set('end_date', `${e.target.value}T${endTimePart}`)} />
              {!form.all_day && (
                <input type="time" value={endTimePart} disabled={!isOwn} style={{ marginTop: 6 }}
                  onChange={e => set('end_date', `${endDatePart}T${e.target.value}`)} />
              )}
            </div>
          </div>

          {/* Descrição */}
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Descrição</label>
            <textarea value={form.description} onChange={e => isOwn && set('description', e.target.value)}
              rows={2} disabled={!isOwn}
              style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit', resize: 'vertical' }}
              placeholder="Detalhes do evento..." />
          </div>

          {/* Local */}
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>📍 Local</label>
            <input value={form.location} onChange={e => isOwn && set('location', e.target.value)}
              placeholder="Sala, endereço, link..." disabled={!isOwn} />
          </div>

          {/* Repetição */}
          {isOwn && (
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label>🔁 Repetição</label>
              <select value={form.repeat_type} onChange={e => set('repeat_type', e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}>
                {REPEAT_OPTIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
          )}

          {/* Visibilidade */}
          {isOwn && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)', background: form.is_public ? 'rgba(212,168,67,0.08)' : 'transparent' }}>
              <input type="checkbox" checked={!!form.is_public} onChange={e => set('is_public', e.target.checked)} />
              <span>🌐 <strong>Evento público</strong> — aparece no calendário de todos <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(título visível, descrição oculta)</span></span>
            </label>
          )}
        </div>

        <div className="modal-footer">
          {initial && isOwn && (
            <button className="btn-admin btn-danger" style={{ marginRight: 'auto' }}
              onClick={() => { if (confirm('Remover este evento?')) onDelete(initial.id); }}>
              🗑️ Remover
            </button>
          )}
          <button className="btn-admin btn-secondary" onClick={onClose}>Cancelar</button>
          {isOwn && (
            <button className="btn-admin btn-primary" onClick={save} disabled={saving}>
              {saving ? 'Salvando...' : '✔ Salvar'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Mini evento pill ─────────────────────────────────────────────────────────
function EventPill({ ev, onClick, isOwn }) {
  return (
    <div onClick={e => { e.stopPropagation(); onClick(ev); }}
      title={ev.title}
      style={{
        background: ev.color || '#C9A84C',
        color: '#fff', fontSize: 11, fontWeight: 600,
        padding: '2px 7px', borderRadius: 10, marginBottom: 2,
        cursor: 'pointer', overflow: 'hidden', whiteSpace: 'nowrap',
        textOverflow: 'ellipsis', maxWidth: '100%',
        opacity: isOwn ? 1 : 0.75,
        boxShadow: `0 2px 8px ${ev.color}55`,
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
      {!isOwn && <span style={{ fontSize: 9 }}>🌐</span>}
      {!ev.all_day && <span style={{ opacity: 0.85, fontSize: 10 }}>{fmtTime(ev.start_date)}</span>}
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis' }}>{ev.title}</span>
    </div>
  );
}

// ── Vista Mês ─────────────────────────────────────────────────────────────────
function MonthView({ year, month, events, currentUserKey, onDayClick, onEventClick, today }) {
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(new Date(year, month, d));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
      {/* Cabeçalho dos dias */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', marginBottom: 4 }}>
        {WEEKDAYS.map(d => (
          <div key={d} style={{ textAlign: 'center', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--text-muted)', padding: '6px 0' }}>{d}</div>
        ))}
      </div>
      {/* Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', flex: 1, gap: 2 }}>
        {cells.map((day, i) => {
          if (!day) return <div key={`e${i}`} />;
          const isToday = isSameDay(day, today);
          const dayEvents = events.filter(ev => eventOnDay(ev, day));
          const isWeekend = day.getDay() === 0 || day.getDay() === 6;
          return (
            <div key={day.toISOString()}
              onClick={() => onDayClick(day)}
              style={{
                minHeight: 90, padding: '6px 4px', borderRadius: 10, cursor: 'pointer',
                background: isToday ? 'rgba(212,168,67,0.12)' : 'var(--surface)',
                border: isToday ? '1.5px solid var(--gold)' : '1px solid var(--border)',
                transition: 'all 0.15s', position: 'relative',
                opacity: isWeekend ? 0.85 : 1,
              }}
              onMouseEnter={e => { if (!isToday) e.currentTarget.style.background = 'rgba(212,168,67,0.05)'; }}
              onMouseLeave={e => { if (!isToday) e.currentTarget.style.background = 'var(--surface)'; }}
            >
              <div style={{
                         fontSize: 13, 
                        fontWeight: isToday ? 700 : 400,
                        marginBottom: 4, 
  textAlign: 'center',
  width: 24, 
  height: 24, 
  borderRadius: '50%', 
  lineHeight: '24px',
  background: isToday ? 'var(--gold)' : 'transparent',
  // Mantivemos apenas a versão que garante contraste com o fundo dourado
  color: isToday ? '#1C1A14' : isWeekend ? 'var(--text-muted)' : 'var(--text)', 
  margin: '0 auto 4px',
}}>{day.getDate()}</div>
              <div style={{ overflow: 'hidden' }}>
                {dayEvents.slice(0, 3).map(ev => (
                  <EventPill key={ev.id} ev={ev} onClick={onEventClick} isOwn={ev.user_key === currentUserKey} />
                ))}
                {dayEvents.length > 3 && (
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', paddingLeft: 4 }}>+{dayEvents.length - 3} mais</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Vista Semana ──────────────────────────────────────────────────────────────
function WeekView({ weekStart, events, currentUserKey, onSlotClick, onEventClick, today }) {
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    return d;
  });
  const hours = Array.from({ length: 24 }, (_, i) => i);

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'auto', flexDirection: 'column' }}>
      {/* Header dias */}
      <div style={{ display: 'grid', gridTemplateColumns: '50px repeat(7,1fr)', borderBottom: '1px solid var(--border)', position: 'sticky', top: 0, background: 'var(--bg)', zIndex: 2 }}>
        <div />
        {days.map(d => {
          const isToday = isSameDay(d, today);
          return (
            <div key={d.toISOString()} style={{ textAlign: 'center', padding: '8px 4px', borderLeft: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{WEEKDAYS[d.getDay()]}</div>
              <div style={{
                fontSize: 20, fontWeight: 700, margin: '2px auto',
                width: 36, height: 36, lineHeight: '36px', borderRadius: '50%',
                background: isToday ? 'var(--gold)' : 'transparent',
                color: isToday ? '#1C1A14' : 'var(--text)',
              }}>{d.getDate()}</div>
            </div>
          );
        })}
      </div>
      {/* Horas */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {hours.map(h => (
          <div key={h} style={{ display: 'grid', gridTemplateColumns: '50px repeat(7,1fr)', minHeight: 60 }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '4px 8px', textAlign: 'right', borderRight: '1px solid var(--border)', position: 'sticky', left: 0 }}>
              {h === 0 ? '' : `${pad(h)}:00`}
            </div>
            {days.map(d => {
              const dayHourEvents = events.filter(ev => {
                if (!eventOnDay(ev, d)) return false;
                const evH = new Date(ev.start_date).getHours();
                return !ev.all_day && evH === h;
              });
              return (
                <div key={d.toISOString()}
                  onClick={() => { const dt = new Date(d); dt.setHours(h); onSlotClick(dt); }}
                  style={{ borderLeft: '1px solid var(--border)', borderBottom: '1px solid rgba(255,255,255,0.03)', padding: '2px', cursor: 'pointer', position: 'relative', minHeight: 60 }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(212,168,67,0.03)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  {dayHourEvents.map(ev => (
                    <EventPill key={ev.id} ev={ev} onClick={onEventClick} isOwn={ev.user_key === currentUserKey} />
                  ))}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Vista Dia ─────────────────────────────────────────────────────────────────
function DayView({ date, events, currentUserKey, onSlotClick, onEventClick }) {
  const dayEvents = events.filter(ev => eventOnDay(ev, date));
  const hours = Array.from({ length: 24 }, (_, i) => i);

  return (
    <div style={{ flex: 1, overflow: 'auto' }}>
      <div style={{ padding: '12px 0', textAlign: 'center', borderBottom: '1px solid var(--border)', marginBottom: 8 }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1 }}>{WEEKDAYS_FULL[date.getDay()]}</div>
        <div style={{ fontSize: 36, fontWeight: 700, color: 'var(--gold)' }}>{date.getDate()}</div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>{MONTHS[date.getMonth()]} {date.getFullYear()}</div>
      </div>
      {/* All day */}
      {dayEvents.filter(ev => ev.all_day).map(ev => (
        <div key={ev.id} onClick={() => onEventClick(ev)} style={{ margin: '0 16px 6px', padding: '8px 14px', borderRadius: 10, background: ev.color, color: '#fff', fontWeight: 600, fontSize: 13, cursor: 'pointer', boxShadow: `0 3px 12px ${ev.color}55` }}>
          {ev.title}
        </div>
      ))}
      {hours.map(h => {
        const hourEvents = dayEvents.filter(ev => !ev.all_day && new Date(ev.start_date).getHours() === h);
        return (
          <div key={h} onClick={() => { const dt = new Date(date); dt.setHours(h); onSlotClick(dt); }}
            style={{ display: 'flex', gap: 12, padding: '0 16px', minHeight: 56, borderBottom: '1px solid rgba(255,255,255,0.04)', cursor: 'pointer', alignItems: 'flex-start', paddingTop: 6 }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(212,168,67,0.04)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <div style={{ fontSize: 12, color: 'var(--text-muted)', width: 44, textAlign: 'right', paddingTop: 2, flexShrink: 0 }}>{`${pad(h)}:00`}</div>
            <div style={{ flex: 1 }}>
              {hourEvents.map(ev => (
                <div key={ev.id} onClick={e => { e.stopPropagation(); onEventClick(ev); }}
                  style={{ padding: '6px 12px', borderRadius: 10, background: ev.color, color: '#fff', fontWeight: 600, fontSize: 13, marginBottom: 4, cursor: 'pointer', boxShadow: `0 3px 12px ${ev.color}55` }}>
                  <div>{ev.title}</div>
                  {ev.location && <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2 }}>📍 {ev.location}</div>}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Agenda (lista) ────────────────────────────────────────────────────────────
function AgendaView({ events, currentUserKey, onEventClick }) {
  const sorted = [...events].sort((a, b) => new Date(a.start_date) - new Date(b.start_date));
  const grouped = {};
  sorted.forEach(ev => {
    const key = ev.start_date.split('T')[0];
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(ev);
  });

  if (sorted.length === 0) return (
    <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
      <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
      <p>Nenhum evento encontrado.</p>
    </div>
  );

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '0 4px' }}>
      {Object.entries(grouped).map(([dateKey, evs]) => {
        const d = new Date(dateKey + 'T12:00:00');
        return (
          <div key={dateKey} style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, color: 'var(--gold)', marginBottom: 8, paddingBottom: 4, borderBottom: '1px solid var(--border)' }}>
              {WEEKDAYS_FULL[d.getDay()]}, {d.getDate()} de {MONTHS[d.getMonth()]} {d.getFullYear()}
            </div>
            {evs.map(ev => (
              <div key={ev.id} onClick={() => onEventClick(ev)}
                style={{ display: 'flex', gap: 14, padding: '10px 14px', borderRadius: 12, cursor: 'pointer', marginBottom: 6, border: '1px solid var(--border)', background: 'var(--surface)', transition: 'all 0.15s', borderLeft: `4px solid ${ev.color}` }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(212,168,67,0.05)'}
                onMouseLeave={e => e.currentTarget.style.background = 'var(--surface)'}
              >
                <div style={{ fontSize: 12, color: 'var(--text-muted)', width: 50, flexShrink: 0, paddingTop: 2 }}>
                  {ev.all_day ? 'Dia todo' : fmtTime(ev.start_date)}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>
                    {ev.user_key !== currentUserKey && <span style={{ fontSize: 11, marginRight: 6 }}>🌐</span>}
                    {ev.title}
                  </div>
                  {ev.description && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{ev.description}</div>}
                  {ev.location && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>📍 {ev.location}</div>}
                </div>
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: ev.color, flexShrink: 0, marginTop: 4, boxShadow: `0 0 8px ${ev.color}` }} />
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ── Componente principal ──────────────────────────────────────────────────────
export default function CalendarioPage() {
  const { user } = useAuth();
  const today = new Date();
  const [view, setView] = useState('month');
  const [currentDate, setCurrentDate] = useState(new Date());
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingEvent, setEditingEvent] = useState(null);
  const [defaultDate, setDefaultDate] = useState(null);

  useEffect(() => { loadEvents(); }, []);

  async function loadEvents() {
    setLoading(true);
    try { setEvents(await api.getCalendarEvents()); }
    catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  async function saveEvent(form) {
    if (editingEvent) await api.updateCalendarEvent(editingEvent.id, form);
    else await api.createCalendarEvent(form);
    setShowModal(false); setEditingEvent(null);
    loadEvents();
  }

  async function deleteEvent(id) {
    await api.deleteCalendarEvent(id);
    setShowModal(false); setEditingEvent(null);
    loadEvents();
  }

  function openNew(date) {
    setDefaultDate(date ? toDateStr(date) : toDateStr(today));
    setEditingEvent(null); setShowModal(true);
  }

  function openEdit(ev) { setEditingEvent(ev); setDefaultDate(null); setShowModal(true); }

  // Navigation
  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  function getWeekStart(d) {
    const s = new Date(d); s.setDate(d.getDate() - d.getDay()); return s;
  }

  function nav(dir) {
    const d = new Date(currentDate);
    if (view === 'month') d.setMonth(d.getMonth() + dir);
    else if (view === 'week') d.setDate(d.getDate() + dir * 7);
    else if (view === 'day') d.setDate(d.getDate() + dir);
    setCurrentDate(d);
  }

  function navTitle() {
    if (view === 'month') return `${MONTHS[month]} ${year}`;
    if (view === 'week') {
      const ws = getWeekStart(currentDate);
      const we = new Date(ws); we.setDate(ws.getDate() + 6);
      return `${ws.getDate()} ${MONTHS[ws.getMonth()].slice(0,3)} – ${we.getDate()} ${MONTHS[we.getMonth()].slice(0,3)} ${year}`;
    }
    if (view === 'day') return `${WEEKDAYS_FULL[currentDate.getDay()]}, ${currentDate.getDate()} de ${MONTHS[month]}`;
    return 'Agenda';
  }

  const myEvents = events.filter(ev => ev.user_key === user.key).length;
  const publicEvents = events.filter(ev => ev.user_key !== user.key).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 56px)', padding: '16px 20px', gap: 12 }}>

      {/* ── Topbar ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>📅 Calendário</h2>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--gold)' }}>{myEvents}</span> seus · <span style={{ opacity: 0.7 }}>{publicEvents} públicos</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* View switcher */}
          <div style={{ display: 'flex', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
            {[['month','Mês'],['week','Semana'],['day','Dia'],['agenda','Agenda']].map(([k,lbl]) => (
              <button key={k} onClick={() => setView(k)} style={{
                padding: '6px 14px', border: 'none', fontFamily: 'inherit', fontSize: 12, fontWeight: view===k?700:400,
                background: view===k ? 'var(--gold)' : 'transparent',
                color: view===k ? '#1C1A14' : 'var(--text)', cursor: 'pointer',
              }}>{lbl}</button>
            ))}
          </div>
          <button className="btn-admin btn-primary" onClick={() => openNew(null)}>+ Evento</button>
        </div>
      </div>

      {/* ── Nav ── */}
      {view !== 'agenda' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={() => nav(-1)} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer', color: 'var(--text)', fontSize: 16 }}>‹</button>
          <button onClick={() => setCurrentDate(new Date())} style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 8, padding: '5px 12px', cursor: 'pointer', color: 'var(--gold)', fontSize: 12, fontWeight: 600 }}>Hoje</button>
          <button onClick={() => nav(1)} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer', color: 'var(--text)', fontSize: 16 }}>›</button>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{navTitle()}</h3>
        </div>
      )}

      {/* ── Content ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>📅</div>
            <p>Carregando eventos...</p>
          </div>
        ) : view === 'month' ? (
          <MonthView year={year} month={month} events={events} currentUserKey={user.key}
            onDayClick={openNew} onEventClick={openEdit} today={today} />
        ) : view === 'week' ? (
          <WeekView weekStart={getWeekStart(currentDate)} events={events} currentUserKey={user.key}
            onSlotClick={openNew} onEventClick={openEdit} today={today} />
        ) : view === 'day' ? (
          <DayView date={currentDate} events={events} currentUserKey={user.key}
            onSlotClick={openNew} onEventClick={openEdit} />
        ) : (
          <AgendaView events={events} currentUserKey={user.key} onEventClick={openEdit} />
        )}
      </div>

      {/* ── Modal ── */}
      {showModal && (
        <EventModal
          initial={editingEvent}
          defaultDate={defaultDate}
          currentUserKey={user.key}
          onClose={() => { setShowModal(false); setEditingEvent(null); }}
          onSave={saveEvent}
          onDelete={deleteEvent}
        />
      )}
    </div>
  );
}
