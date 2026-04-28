import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { timeAgo } from '../utils';

const STATUS_CONFIG = {
  aberta: { label: 'Aberta', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', icon: '🔓' },
  em_andamento: { label: 'Em Andamento', color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', icon: '⏳' },
  resolvida: { label: 'Resolvida', color: '#22c55e', bg: 'rgba(34,197,94,0.12)', icon: '✅' },
};

const CATEGORIAS = [
  'Conduta de colega', 'Conduta de liderança', 'Ambiente de trabalho',
  'Assédio ou discriminação', 'Processos e procedimentos', 'Benefícios',
  'Sugestão de melhoria', 'Outro',
];

export default function OuvidoriaPage() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState('todas');

  const isOuvidor = user.is_ouvidor || user.is_admin || user.is_admin_user;

  useEffect(() => { loadData(); }, []);

  async function loadData() {
    setLoading(true);
    try {
      const data = await api.getOuvidoria();
      setItems(data);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }

  const filtered = items.filter(item => {
    if (filter === 'todas') return true;
    return item.status === filter;
  });

  return (
    <div style={{ padding: '20px 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>📢 Ouvidoria</h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {isOuvidor ? 'Você é Ouvidor — vê todas as reclamações com identidade.' : 'Suas reclamações ficam anônimas para outros.'}
          </p>
        </div>
        <button className="btn-admin btn-primary" onClick={() => setShowNew(true)}>
          + Adicionar Reclamação
        </button>
      </div>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
        {[['todas', '📋 Todas'], ['aberta', '🔓 Abertas'], ['em_andamento', '⏳ Em Andamento'], ['resolvida', '✅ Resolvidas']].map(([k, lbl]) => (
          <button key={k} onClick={() => setFilter(k)} style={{
            padding: '6px 14px', borderRadius: 20, border: '1px solid var(--border)',
            background: filter === k ? 'var(--gold)' : 'var(--surface)',
            color: filter === k ? '#fff' : 'var(--text)', fontWeight: filter === k ? 600 : 400,
            cursor: 'pointer', fontSize: 13, fontFamily: 'inherit',
          }}>{lbl}</button>
        ))}
      </div>

      {/* List */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>Carregando...</div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📭</div>
          <p>Nenhuma reclamação {filter !== 'todas' ? `com status "${filter}"` : ''}</p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {filtered.map(item => (
            <OuvidoriaCard
              key={item.id}
              item={item}
              isOuvidor={isOuvidor}
              currentUser={user}
              onOpen={() => setSelected(item)}
              onRefresh={loadData}
            />
          ))}
        </div>
      )}

      {showNew && <NewReclamacaoModal onClose={() => setShowNew(false)} onSave={async data => { await api.createOuvidoria(data); setShowNew(false); loadData(); }} currentUser={user} />}
      {selected && <ReclamacaoDetail item={items.find(i => i.id === selected.id) || selected} isOuvidor={isOuvidor} currentUser={user} onClose={() => setSelected(null)} onRefresh={() => { loadData(); setSelected(null); }} />}
    </div>
  );
}

function OuvidoriaCard({ item, isOuvidor, currentUser, onOpen, onRefresh }) {
  const sc = STATUS_CONFIG[item.status] || STATUS_CONFIG.aberta;
  const isOwner = item.author_key === currentUser.key;
  const displayName = isOuvidor ? item.author_name : (isOwner ? 'Você' : 'Anônimo');
  const responses = item.responses || [];

  return (
    <div
      onClick={onOpen}
      style={{
        background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12,
        padding: '16px 20px', cursor: 'pointer', transition: 'all 0.2s',
        boxShadow: 'var(--surface-glow)',
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = 'var(--card-glow)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'var(--surface-glow)'}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            padding: '3px 10px', borderRadius: 20, fontSize: 12, fontWeight: 600,
            background: sc.bg, color: sc.color
          }}>{sc.icon} {sc.label}</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', background: 'var(--bg)', padding: '2px 8px', borderRadius: 10 }}>
            {item.category}
          </span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{timeAgo(item.created_at)}</div>
      </div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{displayName}</div>
      <div style={{ fontSize: 13, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {item.text}
      </div>
      {responses.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--gold)' }}>💬 {responses.length} resposta{responses.length > 1 ? 's' : ''}</div>
      )}
    </div>
  );
}

function ReclamacaoDetail({ item, isOuvidor, currentUser, onClose, onRefresh }) {
  const [newReply, setNewReply] = useState('');
  const [statusLoading, setStatusLoading] = useState(false);
  const [replyLoading, setReplyLoading] = useState(false);
  const sc = STATUS_CONFIG[item.status] || STATUS_CONFIG.aberta;
  const responses = item.responses || [];
  const isOwner = item.author_key === currentUser.key;
  const displayName = isOuvidor ? item.author_name : (isOwner ? 'Você' : 'Anônimo');
  const canReply = isOuvidor || isOwner;

  async function changeStatus(status) {
    setStatusLoading(true);
    try { await api.updateOuvidoriaStatus(item.id, status); onRefresh(); }
    catch (e) { alert(e.message); }
    finally { setStatusLoading(false); }
  }

  async function sendReply() {
    if (!newReply.trim()) return;
    setReplyLoading(true);
    try { await api.respondOuvidoria(item.id, newReply); setNewReply(''); onRefresh(); }
    catch (e) { alert(e.message); }
    finally { setReplyLoading(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 620, maxHeight: '92vh', display: 'flex', flexDirection: 'column' }}>
        <div className="modal-header">
          <h3>📢 Reclamação</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div style={{ overflowY: 'auto', flex: 1, padding: '16px 24px' }}>
          {/* Meta */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, alignItems: 'center' }}>
            <span style={{ padding: '4px 12px', borderRadius: 20, background: sc.bg, color: sc.color, fontSize: 13, fontWeight: 600 }}>{sc.icon} {sc.label}</span>
            <span style={{ padding: '4px 10px', borderRadius: 20, background: 'var(--bg)', color: 'var(--text-muted)', fontSize: 12 }}>{item.category}</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>{timeAgo(item.created_at)}</span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: 'var(--gold)' }}>Reclamante: {displayName}</div>
          <div style={{ fontSize: 14, lineHeight: 1.7, marginBottom: 20, whiteSpace: 'pre-wrap' }}>{item.text}</div>

          {/* Status change (ouvidor only) */}
          {isOuvidor && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 20, padding: '12px 0', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: 'var(--text-muted)', alignSelf: 'center' }}>Alterar status:</span>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                <button key={k} disabled={item.status === k || statusLoading} onClick={() => changeStatus(k)} style={{
                  padding: '5px 12px', borderRadius: 16, border: `1px solid ${v.color}`,
                  background: item.status === k ? v.bg : 'transparent', color: v.color,
                  fontSize: 12, fontWeight: 600, cursor: item.status === k ? 'default' : 'pointer', fontFamily: 'inherit',
                }}>{v.icon} {v.label}</button>
              ))}
            </div>
          )}

          {/* Replies */}
          {responses.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.8 }}>💬 Respostas</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {responses.map(r => (
                  <div key={r.id} style={{
                    background: r.is_ouvidor ? 'rgba(212,168,67,0.08)' : 'var(--bg)',
                    border: `1px solid ${r.is_ouvidor ? 'rgba(212,168,67,0.2)' : 'var(--border)'}`,
                    borderRadius: 10, padding: '10px 14px',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: r.is_ouvidor ? 'var(--gold)' : 'var(--text)' }}>
                        {r.is_ouvidor ? '👁️ ' + r.author_name : '👤 Reclamante'}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{timeAgo(r.created_at)}</span>
                    </div>
                    <div style={{ fontSize: 13, lineHeight: 1.6 }}>{r.text}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Reply box */}
          {canReply && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>
                {isOuvidor ? '✍️ Responder como Ouvidor' : '✍️ Adicionar comentário'}
              </div>
              <textarea
                value={newReply}
                onChange={e => setNewReply(e.target.value)}
                rows={4}
                style={{ width: '100%', padding: '10px 14px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: 13, resize: 'vertical', fontFamily: 'inherit' }}
                placeholder="Digite sua resposta..."
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                <button className="btn-admin btn-primary" onClick={sendReply} disabled={replyLoading || !newReply.trim()}>
                  {replyLoading ? 'Enviando...' : '📩 Enviar Resposta'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NewReclamacaoModal({ onClose, onSave, currentUser }) {
  const [form, setForm] = useState({ category: CATEGORIAS[0], text: '', author_display_name: currentUser.name });
  const [saving, setSaving] = useState(false);
  const charLimit = 12000;
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function handleSave() {
    if (!form.text.trim()) return alert('Por favor, descreva a reclamação.');
    setSaving(true);
    try { await onSave(form); }
    catch (e) { alert(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <h3>📢 Nova Reclamação</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div style={{ background: 'rgba(212,168,67,0.08)', border: '1px solid rgba(212,168,67,0.2)', borderRadius: 10, padding: '10px 14px', marginBottom: 16, fontSize: 12, color: 'var(--gold)' }}>
            🔒 Sua identidade é protegida — apenas o Ouvidor pode ver quem você é.
          </div>
          <div className="form-group">
            <label>Seu nome (como aparecerá para o Ouvidor)</label>
            <input value={form.author_display_name} onChange={e => set('author_display_name', e.target.value)} />
          </div>
          <div className="form-group">
            <label>Motivo da Reclamação</label>
            <select value={form.category} onChange={e => set('category', e.target.value)} style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit' }}>
              {CATEGORIAS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label>Descrição da Reclamação</label>
            <textarea
              value={form.text}
              onChange={e => set('text', e.target.value.slice(0, charLimit))}
              rows={7}
              style={{ width: '100%', padding: '10px 14px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontFamily: 'inherit', resize: 'vertical' }}
              placeholder="Descreva detalhadamente a situação..."
            />
            <div style={{ fontSize: 11, color: form.text.length > charLimit * 0.9 ? '#f59e0b' : 'var(--text-muted)', textAlign: 'right', marginTop: 4 }}>
              {form.text.length.toLocaleString()} / {charLimit.toLocaleString()} caracteres
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-admin btn-secondary" onClick={onClose}>Cancelar</button>
          <button className="btn-admin btn-primary" onClick={handleSave} disabled={saving}>{saving ? 'Enviando...' : '📩 Enviar'}</button>
        </div>
      </div>
    </div>
  );
}
