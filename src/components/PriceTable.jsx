import { useState, useEffect } from 'react';
import { api } from '../services/api';
import { useAuth } from '../context/AuthContext';

const CURRENCY = (v) => v != null && v > 0
  ? `R$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`
  : <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>—</span>;

const COLS = [
  { key: 'value_cash',       label: '💵 Dinheiro' },
  { key: 'value_card_pix',   label: '💳 Cartão/Pix' },
  { key: 'value_bradesco',   label: '🏥 Bradesco' },
  { key: 'value_brv',        label: '🏥 BRV' },
  { key: 'value_prefeitura', label: '🏛️ Pref. Maracás' },
];

// ── Modal de médico ──────────────────────────────────────────────────────────
function DoctorModal({ initial, folderId, onClose, onSave }) {
  const [form, setForm] = useState({
    name: '', specialty: '', crm: '', rqe: '', folder_id: folderId,
    ...(initial || {}),
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function save() {
    if (!form.name.trim()) return alert('Nome do médico obrigatório.');
    setSaving(true);
    try { await onSave(form); } catch (e) { alert(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 480 }}>
        <div className="modal-header">
          <h3>{initial ? '✏️ Editar Médico' : '➕ Novo Médico'}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <label>Nome do Médico *</label>
            <input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Dr. João Silva" />
          </div>
          <div className="form-group">
            <label>Especialidade</label>
            <input value={form.specialty} onChange={e => set('specialty', e.target.value)} placeholder="Cardiologia, Dermatologia..." />
          </div>
          <div className="admin-form-row">
            <div className="form-group">
              <label>CRM <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(opcional)</span></label>
              <input value={form.crm} onChange={e => set('crm', e.target.value)} placeholder="CRM/BA 00000" />
            </div>
            <div className="form-group">
              <label>RQE <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>(opcional)</span></label>
              <input value={form.rqe} onChange={e => set('rqe', e.target.value)} placeholder="RQE 00000" />
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-admin btn-secondary" onClick={onClose}>Cancelar</button>
          <button className="btn-admin btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Salvando...' : '✔ Salvar'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Modal de procedimento ────────────────────────────────────────────────────
function ProcedureModal({ initial, doctorId, onClose, onSave }) {
  const [form, setForm] = useState({
    name: '', value_cash: '', value_card_pix: '', value_bradesco: '',
    value_brv: '', value_prefeitura: '', doctor_id: doctorId,
    ...(initial ? {
      ...initial,
      value_cash: initial.value_cash || '',
      value_card_pix: initial.value_card_pix || '',
      value_bradesco: initial.value_bradesco || '',
      value_brv: initial.value_brv || '',
      value_prefeitura: initial.value_prefeitura || '',
    } : {}),
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  async function save() {
    if (!form.name.trim()) return alert('Nome do procedimento obrigatório.');
    setSaving(true);
    try {
      await onSave({
        ...form,
        value_cash: parseFloat(form.value_cash) || 0,
        value_card_pix: parseFloat(form.value_card_pix) || 0,
        value_bradesco: parseFloat(form.value_bradesco) || 0,
        value_brv: parseFloat(form.value_brv) || 0,
        value_prefeitura: parseFloat(form.value_prefeitura) || 0,
      });
    } catch (e) { alert(e.message); setSaving(false); }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <h3>{initial ? '✏️ Editar Procedimento' : '➕ Novo Procedimento'}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <label>Nome do Procedimento *</label>
            <input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Consulta, Exame, Cirurgia..." />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {COLS.map(col => (
              <div className="form-group" key={col.key}>
                <label>{col.label}</label>
                <input
                  type="number" step="0.01" min="0"
                  value={form[col.key]}
                  onChange={e => set(col.key, e.target.value)}
                  placeholder="0,00"
                  style={{ width: '100%' }}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-admin btn-secondary" onClick={onClose}>Cancelar</button>
          <button className="btn-admin btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Salvando...' : '✔ Salvar'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Card de médico com tabela ─────────────────────────────────────────────────
function DoctorCard({ doctor, canAdmin, onEdit, onDelete, onRefresh }) {
  const [procedures, setProcedures] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showProcModal, setShowProcModal] = useState(false);
  const [editingProc, setEditingProc] = useState(null);

  useEffect(() => { loadProcedures(); }, [doctor.id]);

  async function loadProcedures() {
    setLoading(true);
    try {
      const data = await api.getPriceProcedures(doctor.id);
      setProcedures(data);
    } catch {}
    finally { setLoading(false); }
  }

  async function saveProc(form) {
    if (editingProc) {
      await api.updatePriceProcedure(editingProc.id, form);
    } else {
      await api.createPriceProcedure({ ...form, doctor_id: doctor.id });
    }
    setShowProcModal(false);
    setEditingProc(null);
    loadProcedures();
  }

  async function deleteProc(id) {
    if (!confirm('Remover este procedimento?')) return;
    await api.deletePriceProcedure(id);
    loadProcedures();
  }

  return (
    <div style={{
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 14, marginBottom: 20, overflow: 'hidden',
      boxShadow: 'var(--card-glow)',
    }}>
      {/* Header do médico */}
      <div style={{
        padding: '16px 20px', background: 'linear-gradient(135deg, rgba(212,168,67,0.08), transparent)',
        borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10,
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 22 }}>👨‍⚕️</span>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{doctor.name}</div>
              {doctor.specialty && (
                <div style={{ fontSize: 12, color: 'var(--gold)', fontWeight: 500, marginTop: 1 }}>{doctor.specialty}</div>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap' }}>
            {doctor.crm && (
              <span style={{ fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 10, padding: '2px 8px', color: 'var(--text-muted)' }}>
                🪪 {doctor.crm}
              </span>
            )}
            {doctor.rqe && (
              <span style={{ fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 10, padding: '2px 8px', color: 'var(--text-muted)' }}>
                📋 RQE {doctor.rqe}
              </span>
            )}
          </div>
        </div>
        {canAdmin && (
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn-admin btn-primary" style={{ padding: '5px 12px', fontSize: 12 }}
              onClick={() => { setEditingProc(null); setShowProcModal(true); }}>
              + Procedimento
            </button>
            <button className="btn-admin btn-secondary" style={{ padding: '5px 10px', fontSize: 12 }} onClick={onEdit}>✏️</button>
            <button className="btn-admin btn-danger" style={{ padding: '5px 10px', fontSize: 12 }} onClick={onDelete}>🗑️</button>
          </div>
        )}
      </div>

      {/* Tabela de procedimentos */}
      {loading ? (
        <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Carregando...</div>
      ) : procedures.length === 0 ? (
        <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
          {canAdmin ? '➕ Clique em "+ Procedimento" para adicionar.' : 'Nenhum procedimento cadastrado.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--bg)' }}>
                <th style={{ padding: '10px 16px', textAlign: 'left', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>
                  Procedimento
                </th>
                {COLS.map(col => (
                  <th key={col.key} style={{ padding: '10px 14px', textAlign: 'right', fontWeight: 600, fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>
                    {col.label}
                  </th>
                ))}
                {canAdmin && (
                  <th style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', width: 60 }} />
                )}
              </tr>
            </thead>
            <tbody>
              {procedures.map((proc, i) => (
                <tr key={proc.id} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)', transition: 'background 0.15s' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(212,168,67,0.05)'}
                  onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)'}
                >
                  <td style={{ padding: '10px 16px', fontWeight: 500, borderBottom: '1px solid var(--border)' }}>
                    {proc.name}
                  </td>
                  {COLS.map(col => (
                    <td key={col.key} style={{ padding: '10px 14px', textAlign: 'right', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>
                      {CURRENCY(proc[col.key])}
                    </td>
                  ))}
                  {canAdmin && (
                    <td style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)', textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                        <button onClick={() => { setEditingProc(proc); setShowProcModal(true); }}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, opacity: 0.6 }}
                          title="Editar">✏️</button>
                        <button onClick={() => deleteProc(proc.id)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, opacity: 0.6 }}
                          title="Remover">🗑️</button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showProcModal && (
        <ProcedureModal
          initial={editingProc}
          doctorId={doctor.id}
          onClose={() => { setShowProcModal(false); setEditingProc(null); }}
          onSave={saveProc}
        />
      )}
    </div>
  );
}

// ── Componente principal exportado ───────────────────────────────────────────
export default function PriceTable({ folderId }) {
  const { canAdmin } = useAuth();
  const [doctors, setDoctors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDoctorModal, setShowDoctorModal] = useState(false);
  const [editingDoctor, setEditingDoctor] = useState(null);

  useEffect(() => { loadDoctors(); }, [folderId]);

  async function loadDoctors() {
    setLoading(true);
    try {
      const data = await api.getPriceDoctors(folderId);
      setDoctors(data);
    } catch {}
    finally { setLoading(false); }
  }

  async function saveDoctor(form) {
    if (editingDoctor) {
      await api.updatePriceDoctor(editingDoctor.id, form);
    } else {
      await api.createPriceDoctor({ ...form, folder_id: folderId });
    }
    setShowDoctorModal(false);
    setEditingDoctor(null);
    loadDoctors();
  }

  async function deleteDoctor(id) {
    if (!confirm('Remover este médico e todos os seus procedimentos?')) return;
    await api.deletePriceDoctor(id);
    loadDoctors();
  }

  async function downloadTable() {
  try {
    const { default: jsPDF } = await import('jspdf');
    const { default: autoTable } = await import('jspdf-autotable');

    const doc = new jsPDF({ orientation: 'landscape' });

    doc.setFontSize(14);
    doc.text('Tabela de Preços - Clínica Diálogos', 14, 15);

    for (const doctor of doctors) {
      // Busca os procedimentos de cada médico
      const procedures = await api.getPriceProcedures(doctor.id);

      doc.setFontSize(11);
      doc.setTextColor(212, 168, 67); // dourado
      doc.text(`${doctor.name}${doctor.specialty ? ` — ${doctor.specialty}` : ''}`, 14, doc.lastAutoTable?.finalY + 14 || 25);
      doc.setTextColor(0, 0, 0);

      autoTable(doc, {
        startY: (doc.lastAutoTable?.finalY || 20) + 18,
        head: [['Procedimento', 'Dinheiro', 'Cartão/PIX', 'Bradesco', 'BRV', 'Pref. Maracás']],
        body: procedures.map(p => [
          p.name,
          p.value_cash > 0 ? `R$ ${Number(p.value_cash).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—',
          p.value_card_pix > 0 ? `R$ ${Number(p.value_card_pix).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—',
          p.value_bradesco > 0 ? `R$ ${Number(p.value_bradesco).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—',
          p.value_brv > 0 ? `R$ ${Number(p.value_brv).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—',
          p.value_prefeitura > 0 ? `R$ ${Number(p.value_prefeitura).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}` : '—',
        ]),
        theme: 'striped',
        margin: { left: 14, right: 14 },
      });
    }

    doc.save(`tabela_precos_${new Date().toISOString().slice(0, 10)}.pdf`);
  } catch (e) {
    alert(e.message || 'Erro ao gerar PDF.');
  }
}
  if (loading) return (
    <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)' }}>
      <div style={{ fontSize: 32, marginBottom: 8 }}>💊</div>
      <p>Carregando tabela de preços...</p>
    </div>
  );

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {doctors.length} médico{doctors.length !== 1 ? 's' : ''} cadastrado{doctors.length !== 1 ? 's' : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn-admin btn-secondary" onClick={downloadTable}>
            ⬇️ Baixar Tabela de Preços
          </button>
          {canAdmin && (
            <button className="btn-admin btn-primary" onClick={() => { setEditingDoctor(null); setShowDoctorModal(true); }}>
              👨‍⚕️ + Adicionar Médico
            </button>
          )}
        </div>
      </div>

      {/* Lista de médicos */}
      {doctors.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '50px 20px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>👨‍⚕️</div>
          <p style={{ fontSize: 14 }}>Nenhum médico cadastrado ainda.</p>
          {canAdmin && <p style={{ fontSize: 12, marginTop: 4 }}>Clique em "+ Adicionar Médico" para começar.</p>}
        </div>
      ) : (
        doctors.map(doc => (
          <DoctorCard
            key={doc.id}
            doctor={doc}
            canAdmin={canAdmin}
            onEdit={() => { setEditingDoctor(doc); setShowDoctorModal(true); }}
            onDelete={() => deleteDoctor(doc.id)}
            onRefresh={loadDoctors}
          />
        ))
      )}

      {showDoctorModal && (
        <DoctorModal
          initial={editingDoctor}
          folderId={folderId}
          onClose={() => { setShowDoctorModal(false); setEditingDoctor(null); }}
          onSave={saveDoctor}
        />
      )}
    </div>
  );
}
