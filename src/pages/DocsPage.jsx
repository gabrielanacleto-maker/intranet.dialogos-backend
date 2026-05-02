import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { formatBytes, getFileIcon, LEVEL_LABEL } from '../utils';
import PriceTable from '../components/PriceTable';

const LEVEL_ACCESS = { all: 0, dourado: 1, platina: 2, diamante: 3, rh: 99 };

function canAccessFolder(folder, user) {
  if (folder.level === 'all') return true;
  if (folder.level === 'rh') return user.is_rh || user.is_admin;
  const userOrder = LEVEL_ACCESS[user.level] ?? 0;
  return userOrder >= (LEVEL_ACCESS[folder.level] ?? 0);
}

export default function DocsPage() {
  const { user, canAdmin } = useAuth();
  const toast = useToast();
  const [folders, setFolders] = useState([]);
  const [openFolder, setOpenFolder] = useState(null);
  const [files, setFiles] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [editingFolder, setEditingFolder] = useState(null);
  const [form, setForm] = useState({ name: '', icon: '📁', level: 'all', drive_link: '' });
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => { loadFolders(); }, []);

  async function loadFolders() {
    try {
      const data = await api.getFolders();
      setFolders(data);
    } catch (err) { toast(err.message, 'error'); }
  }

  async function openFolderView(folder) {
    if (!canAccessFolder(folder, user)) {
      toast('Você não tem permissão para acessar esta pasta.', 'error');
      return;
    }
    setOpenFolder(folder);
    try {
      const data = await api.getFolderFiles(folder.id);
      setFiles(data);
    } catch (err) { toast(err.message, 'error'); }
  }

  async function saveFolder() {
    if (!form.name.trim()) return toast('Nome da pasta obrigatório.', 'error');
    setSaving(true);
    try {
      if (editingFolder) {
        await api.updateFolder(editingFolder.id, form);
        toast('Pasta atualizada!', 'success');
      } else {
        await api.createFolder(form);
        toast('Pasta criada!', 'success');
      }
      setShowModal(false);
      setEditingFolder(null);
      setForm({ name: '', icon: '📁', level: 'all', drive_link: '' });
      await loadFolders();
    } catch (err) { toast(err.message, 'error'); }
    finally { setSaving(false); }
  }

  async function deleteFolder(id) {
    if (!confirm('Remover esta pasta e todos os seus arquivos?')) return;
    try {
      await api.deleteFolder(id);
      toast('Pasta removida.', 'success');
      loadFolders();
    } catch (err) { toast(err.message, 'error'); }
  }

  async function uploadFile(file) {
    if (!openFolder) return;
    setUploading(true);
    try {
      await api.uploadFolderFile(openFolder.id, file);
      toast(`"${file.name}" enviado!`, 'success');
      const data = await api.getFolderFiles(openFolder.id);
      setFiles(data);
    } catch (err) { toast(err.message, 'error'); }
    finally { setUploading(false); }
  }

  async function handleFileInput(e) {
    for (const f of e.target.files) await uploadFile(f);
    e.target.value = '';
  }

  async function deleteFile(fileId) {
    if (!confirm('Remover este arquivo?')) return;
    try {
      await api.deleteFolderFile(openFolder.id, fileId);
      setFiles(f => f.filter(x => x.id !== fileId));
      toast('Arquivo removido.', 'success');
    } catch (err) { toast(err.message, 'error'); }
  }

  function openEditModal(folder) {
    setEditingFolder(folder);
    setForm({ name: folder.name, icon: folder.icon, level: folder.level, drive_link: folder.drive_link || '' });
    setShowModal(true);
  }

  // Folder list view
  if (!openFolder) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div className="section-title" style={{ marginBottom: 0 }}>Documentações</div>
          {canAdmin && (
            <button className="btn-admin btn-primary" onClick={() => { setEditingFolder(null); setForm({ name: '', icon: '📁', level: 'all', drive_link: '' }); setShowModal(true); }}>
              + Nova Pasta
            </button>
          )}
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>
          Pastas marcadas com 🔒 exigem nível de acesso específico.
        </p>

        <div className="docs-grid">
          {folders.map(folder => {
            const accessible = canAccessFolder(folder, user);
            return (
              <div key={folder.id} style={{ position: 'relative' }}>
                <div
                  className="doc-folder-card"
                  onClick={() => openFolderView(folder)}
                  style={{ opacity: accessible ? 1 : 0.5 }}
                >
                  <span className="doc-folder-icon">{folder.icon}</span>
                  <div className="doc-folder-name">{folder.name}</div>
                  <div className="doc-folder-level">
                    {!accessible && '🔒 '}{LEVEL_LABEL[folder.level] || folder.level}
                  </div>
                </div>
                {canAdmin && (
                  <div style={{ display: 'flex', gap: 4, marginTop: 6, justifyContent: 'center' }}>
                    <button className="btn-admin btn-secondary" style={{ padding: '3px 8px', fontSize: 11 }} onClick={() => openEditModal(folder)}>✏️</button>
                    <button className="btn-admin btn-danger" style={{ padding: '3px 8px', fontSize: 11 }} onClick={() => deleteFolder(folder.id)}>🗑️</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {showModal && (
          <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
            <div className="modal-card" style={{ maxWidth: 480 }}>
              <div className="modal-header">
                <div className="modal-title">{editingFolder ? 'Editar Pasta' : 'Nova Pasta'}</div>
                <button className="modal-close" onClick={() => setShowModal(false)}>✕</button>
              </div>
              <div className="admin-form">
                <div className="admin-field">
                  <label>Nome da pasta</label>
                  <input type="text" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Ex: Protocolos Clínicos" />
                </div>
                <div className="admin-form-row">
                  <div className="admin-field">
                    <label>Ícone (emoji)</label>
                    <input type="text" value={form.icon} onChange={e => setForm(f => ({ ...f, icon: e.target.value }))} placeholder="📋" maxLength={2} />
                  </div>
                  <div className="admin-field">
                    <label>Nível de acesso</label>
                    <select value={form.level} onChange={e => setForm(f => ({ ...f, level: e.target.value }))}>
                      <option value="all">🌐 Todos</option>
                      <option value="dourado">🟡 Dourado</option>
                      <option value="platina">⬜ Platina</option>
                      <option value="diamante">💎 Diamante</option>
                      <option value="rh">🧬 Somente RH</option>
                    </select>
                  </div>
                </div>
                <div className="admin-field">
                  <label>Link do Google Drive (opcional)</label>
                  <input type="url" value={form.drive_link} onChange={e => setForm(f => ({ ...f, drive_link: e.target.value }))} placeholder="https://drive.google.com/..." />
                </div>
              </div>
              <div className="modal-footer">
                <button className="btn-admin btn-secondary" onClick={() => setShowModal(false)}>Cancelar</button>
                <button className="btn-admin btn-primary" onClick={saveFolder} disabled={saving}>
                  {saving ? 'Salvando...' : 'Salvar'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Inside folder view
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button className="btn-admin btn-secondary" onClick={() => setOpenFolder(null)} style={{ padding: '6px 12px', fontSize: 16 }}>←</button>
          <span style={{ fontSize: 28 }}>{openFolder.icon}</span>
          <div className="section-title" style={{ marginBottom: 0 }}>{openFolder.name}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {openFolder.drive_link && (
            <a href={openFolder.drive_link} target="_blank" rel="noopener noreferrer"
              style={{ padding: '8px 14px', background: 'rgba(110,175,212,0.12)', color: 'var(--diam)', border: '1px solid var(--diam)', borderRadius: 'var(--radius-sm)', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>
              🔗 Abrir no Google Drive
            </a>
          )}
          {canAdmin && (
            <label className="btn-admin btn-primary" style={{ cursor: 'pointer' }}>
              {uploading ? '⏳ Enviando...' : '📎 + Adicionar Documento'}
              <input type="file" hidden multiple
                accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.jpg,.jpeg,.png,.gif,.webp,.zip,.xml,.json,.mp4,.mp3"
                onChange={handleFileInput}
              />
            </label>
          )}
        </div>
      </div>

      {/* Tipos aceitos */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        {['PDF','Word','Excel','PowerPoint','XML','Imagens','Vídeo','ZIP'].map(t => (
          <span key={t} style={{ padding: '2px 8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 20, fontSize: 11, color: 'var(--text-muted)' }}>
            {t}
          </span>
        ))}
      </div>

      {/* Drop zone */}
      {canAdmin && (
        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={async e => {
            e.preventDefault(); setDragging(false);
            for (const f of e.dataTransfer.files) await uploadFile(f);
          }}
          style={{
            border: `2px dashed ${dragging ? 'var(--gold)' : 'var(--border)'}`,
            borderRadius: 'var(--radius)', padding: '32px', textAlign: 'center',
            marginBottom: 20, cursor: 'pointer', transition: 'all 0.2s',
            background: dragging ? 'rgba(201,168,76,0.06)' : 'transparent',
            color: 'var(--text-muted)',
          }}
        >
          <div style={{ fontSize: 36, marginBottom: 8 }}>📂</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Arraste arquivos aqui ou use o botão acima</div>
          <div style={{ fontSize: 12 }}>PDF, Word, Excel, PowerPoint, XML, imagens e muito mais</div>
        </div>
      )}

      {/* Tabela de Preços especial */}
      {openFolder.name.toLowerCase().includes('preço') || openFolder.name.toLowerCase().includes('preco') ? (
        <PriceTable folderId={openFolder.id} />
      ) : (
      <>
      {/* Files list */}
      {files.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 40, marginBottom: 10 }}>📭</div>
          <p style={{ fontSize: 14 }}>Nenhum documento nesta pasta ainda.</p>
          {canAdmin && <p style={{ fontSize: 12, marginTop: 4 }}>Use o botão acima para adicionar.</p>}
        </div>
      ) : (
        <div>
          {files.map(f => (
            <div key={f.id} className="file-item">
              <div className="file-icon">{getFileIcon(f.name, f.mime_type)}</div>
              <div className="file-meta">
                <div className="file-name">{f.name}</div>
                <div className="file-size">{formatBytes(f.size)} · {f.uploaded_by} · {new Date(f.created_at).toLocaleDateString('pt-BR')}</div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <a href={api.assetUrl(f.url)} target="_blank" rel="noopener noreferrer" download={f.name}
                  className="btn-admin btn-secondary" style={{ padding: '5px 10px', fontSize: 12, textDecoration: 'none' }}>
                  ⬇ Baixar
                </a>
                {canAdmin && (
                  <button className="btn-admin btn-danger" style={{ padding: '5px 8px', fontSize: 12 }} onClick={() => deleteFile(f.id)}>🗑️</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      </>
      )}
    </div>
  );
}
