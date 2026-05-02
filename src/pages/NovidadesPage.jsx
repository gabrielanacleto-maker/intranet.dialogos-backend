import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import FeedPage from './FeedPage';

export default function NovidadesPage() {
  const { user, canPostNovidades, canAdmin } = useAuth();
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [current, setCurrent] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [form, setForm] = useState({ tag: 'Novidades', title: '', subtitle: '', content: '', image_url: '' });
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploadingImg, setUploadingImg] = useState(false);
  const [showDetail, setShowDetail] = useState(null);
  const timerRef = useRef();

  useEffect(() => { loadItems(); }, []);
  useEffect(() => {
    if (items.length > 1) {
      timerRef.current = setInterval(() => setCurrent(c => (c + 1) % items.length), 5000);
      return () => clearInterval(timerRef.current);
    }
  }, [items.length]);

  async function loadItems() {
    try { setItems(await api.getMural()); } catch (err) { toast(err.message, 'error'); }
  }

  async function handleImageSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    setImageFile(file);
    setImagePreview(URL.createObjectURL(file));
  }

  async function save() {
    if (!form.title.trim()) return toast('Título obrigatório.', 'error');
    setSaving(true);
    try {
      let imageUrl = form.image_url;
      if (imageFile) {
        setUploadingImg(true);
        const res = await api.uploadMuralImage(imageFile);
        imageUrl = res.url;
        setUploadingImg(false);
      }
      if (editingItem) {
        // Re-create (simple approach — delete + create)
        await api.deleteMural(editingItem.id);
      }
      await api.createMural({ ...form, image_url: imageUrl });
      toast('Publicado no mural!', 'success');
      setShowModal(false);
      setEditingItem(null);
      setImageFile(null);
      setImagePreview('');
      setForm({ tag: 'Novidades', title: '', subtitle: '', content: '', image_url: '' });
      loadItems();
    } catch (err) { toast(err.message, 'error'); }
    finally { setSaving(false); setUploadingImg(false); }
  }

  async function deleteItem(id) {
    if (!confirm('Remover esta publicação do mural?')) return;
    try {
      await api.deleteMural(id);
      toast('Removido.', 'success');
      setItems(it => it.filter(x => x.id !== id));
    } catch (err) { toast(err.message, 'error'); }
  }

  const slide = items[current];
  const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="section-title" style={{ marginBottom: 0 }}>✨ Feed Novidades Diálogos</div>
        {canPostNovidades && (
          <button className="btn-admin btn-primary" onClick={() => { setEditingItem(null); setForm({ tag: 'Novidades', title: '', subtitle: '', content: '', image_url: '' }); setImageFile(null); setImagePreview(''); setShowModal(true); }}>
            + Nova Publicação
          </button>
        )}
      </div>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16, fontSize: 13 }}>
        Comunicados oficiais, novidades de RH, treinamentos e eventos em destaque.
      </p>

      {/* Carousel */}
      {items.length > 0 && (
        <div className="mural-container" style={{ marginBottom: 24 }}>
          {items.map((item, i) => {
            const imgSrc = item.image_url ? (item.image_url.startsWith('http') ? item.image_url : `${BASE}${item.image_url}`) : '';
            return (
              <div
                key={item.id}
                className={`mural-slide${i === current ? ' active' : ''}`}
                style={{ backgroundImage: imgSrc ? `url(${imgSrc})` : 'linear-gradient(135deg, #2A2618, #3D3220)', backgroundSize: 'cover', backgroundPosition: 'center' }}
                onClick={() => setShowDetail(item)}
              >
                <div className="mural-gradient" />
                <div className="mural-content">
                  <span className="mural-tag">{item.tag}</span>
                  <div className="mural-title">{item.title}</div>
                  {item.subtitle && <div className="mural-sub">{item.subtitle}</div>}
                </div>
              </div>
            );
          })}
          <div className="mural-nav">
            {items.map((_, i) => (
              <button key={i} className={`mural-dot${i === current ? ' active' : ''}`} onClick={e => { e.stopPropagation(); setCurrent(i); clearInterval(timerRef.current); }} />
            ))}
          </div>
        </div>
      )}

      {items.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)', background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)', marginBottom: 24 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>📢</div>
          <p>Nenhuma publicação no mural ainda.</p>
          {canPostNovidades && <p style={{ fontSize: 12, marginTop: 4 }}>Use o botão acima para adicionar a primeira.</p>}
        </div>
      )}

      {/* Management list */}
      {canAdmin && items.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Gerenciar Publicações do Mural</div>
          {items.map(item => {
            const imgSrc = item.image_url ? (item.image_url.startsWith('http') ? item.image_url : `${BASE}${item.image_url}`) : '';
            return (
              <div key={item.id} style={{ display: 'flex', gap: 14, alignItems: 'center', padding: '12px 16px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', marginBottom: 8 }}>
                {imgSrc && <img src={imgSrc} alt="" style={{ width: 60, height: 45, objectFit: 'cover', borderRadius: 6, flexShrink: 0, background: 'var(--border)' }} onError={e => e.target.style.display = 'none'} loading="lazy" />}
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{item.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{item.tag} · {new Date(item.created_at).toLocaleDateString('pt-BR')}</div>
                </div>
                <button className="btn-admin btn-danger" style={{ padding: '5px 8px', fontSize: 12 }} onClick={() => deleteItem(item.id)}>🗑️</button>
              </div>
            );
          })}
        </div>
      )}

      {/* Feed of novidades posts */}
      <div style={{ fontFamily: 'Playfair Display', fontSize: 16, fontWeight: 600, marginBottom: 14 }}>Publicações do Feed</div>
      <FeedPage feedType="novidades" />

      {/* Create/Edit modal */}
      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal-card" style={{ maxWidth: 600 }}>
            <div className="modal-header">
              <div className="modal-title">Publicação no Mural</div>
              <button className="modal-close" onClick={() => setShowModal(false)}>✕</button>
            </div>
            <div className="admin-form">
              <div className="admin-field">
                <label>Categoria / Tag</label>
                <select value={form.tag} onChange={e => setForm(f => ({ ...f, tag: e.target.value }))}>
                  <option value="Novidades">✨ Novidades</option>
                  <option value="Comunicado">📢 Comunicado</option>
                  <option value="Treinamento">🎓 Treinamento</option>
                  <option value="Evento">📅 Evento</option>
                  <option value="Equipe">👥 Equipe</option>
                  <option value="RH">🧬 Recursos Humanos</option>
                </select>
              </div>
              <div className="admin-field">
                <label>Título Principal</label>
                <input type="text" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="Ex: Grande Inauguração" />
              </div>
              <div className="admin-field">
                <label>Subtítulo (breve descrição)</label>
                <input type="text" value={form.subtitle} onChange={e => setForm(f => ({ ...f, subtitle: e.target.value }))} placeholder="Ex: Venha conferir..." />
              </div>
              <div className="admin-field">
                <label>Imagem de Fundo (do seu computador)</label>
                <input type="file" accept="image/*" onChange={handleImageSelect}
                  style={{ width: '100%', padding: '9px', borderRadius: 8, border: '1.5px solid var(--border)', background: 'var(--bg)', fontFamily: 'inherit', fontSize: 13 }} />
                {imagePreview && (
                  <div style={{ marginTop: 8 }}>
                    <img src={imagePreview} alt="Preview" style={{ width: '100%', maxHeight: 180, objectFit: 'cover', borderRadius: 8, display: 'block' }} />
                    <button className="btn-admin btn-secondary" style={{ padding: '5px 10px', fontSize: 12, marginTop: 6 }} onClick={() => { setImageFile(null); setImagePreview(''); }}>
                      Remover imagem
                    </button>
                  </div>
                )}
              </div>
              <div className="admin-field">
                <label>Conteúdo Completo (detalhes ao clicar)</label>
                <textarea value={form.content} onChange={e => setForm(f => ({ ...f, content: e.target.value }))} rows={5}
                  style={{ width: '100%', padding: 10, borderRadius: 8, border: '1.5px solid var(--border)', fontFamily: 'inherit', resize: 'vertical', fontSize: 13, background: 'var(--bg)', color: 'var(--text)' }}
                  placeholder="Detalhes da publicação..." />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-admin btn-secondary" onClick={() => setShowModal(false)}>Cancelar</button>
              <button className="btn-admin btn-primary" onClick={save} disabled={saving}>
                {saving ? (uploadingImg ? '⏳ Enviando imagem...' : '💾 Salvando...') : 'Salvar na Intranet'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Detail modal */}
      {showDetail && (
        <div className="modal-overlay" onClick={() => setShowDetail(null)}>
          <div className="modal-card" style={{ maxWidth: 700, padding: 0, overflow: 'hidden' }} onClick={e => e.stopPropagation()}>
            <div style={{ height: 250, position: 'relative', background: '#000' }}>
              {showDetail.image_url && (
                <img src={showDetail.image_url.startsWith('http') ? showDetail.image_url : `${BASE}${showDetail.image_url}`} style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.7 }} alt="" onError={e => e.target.style.display = 'none'} />
              )}
              <button className="modal-close" onClick={() => setShowDetail(null)} style={{ position: 'absolute', top: 15, right: 15, background: 'rgba(0,0,0,0.5)', color: '#fff' }}>✕</button>
              <div style={{ position: 'absolute', bottom: 20, left: 24, color: '#fff' }}>
                <span className="mural-tag" style={{ marginBottom: 8, display: 'inline-block' }}>{showDetail.tag}</span>
                <h2 style={{ fontFamily: 'Playfair Display', fontSize: 24 }}>{showDetail.title}</h2>
              </div>
            </div>
            <div style={{ padding: 30, background: 'var(--surface)' }}>
              {showDetail.subtitle && <p style={{ fontSize: 15, color: 'var(--text-muted)', marginBottom: 16 }}>{showDetail.subtitle}</p>}
              <div style={{ lineHeight: 1.8, color: 'var(--text)', fontSize: 15, whiteSpace: 'pre-wrap' }}>
                {showDetail.content || 'Sem conteúdo adicional.'}
              </div>
              <div style={{ marginTop: 30, paddingTop: 20, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
                <button className="btn-admin btn-primary" onClick={() => setShowDetail(null)}>Entendido</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
