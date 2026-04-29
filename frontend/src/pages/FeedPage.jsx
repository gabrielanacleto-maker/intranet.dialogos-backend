import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { api } from '../services/api';
import { AV_COLORS, timeAgo, buildEmbedHtml } from '../utils';
import MoodWidget from '../components/MoodWidget';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ── Emojis ───────────────────────────────────────────────────────────────────
const EMOJI_LIST = [
  '😀','😂','😍','🥰','😎','🤩','😊','🙏','👏','❤️',
  '🔥','✨','🎉','💪','👍','🫶','😅','🤔','😢','😮',
  '💼','📋','📅','🏥','💊','🩺','🧬','📢','🌟','⭐',
  '✅','❌','⚠️','💡','🎯','📌','🔔','💬','📣','🏆',
];

function EmojiPicker({ onSelect, onClose }) {
  const ref = useRef();
  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) onClose(); }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div ref={ref} style={{
      position: 'absolute', zIndex: 100, background: 'var(--surface)',
      border: '1px solid var(--border)', borderRadius: 12, padding: 10,
      display: 'grid', gridTemplateColumns: 'repeat(10, 1fr)', gap: 4,
      boxShadow: '0 8px 32px rgba(0,0,0,0.3)', bottom: 'calc(100% + 6px)', right: 0,
      width: 280,
    }}>
      {EMOJI_LIST.map(e => (
        <button key={e} onClick={() => onSelect(e)} style={{
          background: 'none', border: 'none', cursor: 'pointer', fontSize: 18,
          padding: 4, borderRadius: 6, lineHeight: 1,
          transition: 'background 0.1s',
        }}
          onMouseEnter={el => el.currentTarget.style.background = 'rgba(201,168,76,0.15)'}
          onMouseLeave={el => el.currentTarget.style.background = 'none'}
        >{e}</button>
      ))}
    </div>
  );
}

// ── Tipo de comunicado ────────────────────────────────────────────────────────
function getComunicadoStyle(tipo) {
  if (tipo === 'diretoria') return {
    border: '2px solid #ff2d7a',
    background: 'linear-gradient(135deg, rgba(255,45,122,0.13) 0%, rgba(255,45,122,0.04) 100%)',
    boxShadow: '0 0 24px rgba(255,45,122,0.35), inset 0 0 40px rgba(255,45,122,0.06)',
    labelBg: 'linear-gradient(90deg, #ff2d7a, #ff6eb0)',
    labelText: '📢 Comunicado da Diretoria',
    labelColor: '#fff',
    glow: '0 0 16px rgba(255,45,122,0.7)',
  };
  if (tipo === 'lideranca') return {
    border: '2px solid #a855f7',
    background: 'linear-gradient(135deg, rgba(168,85,247,0.13) 0%, rgba(168,85,247,0.04) 100%)',
    boxShadow: '0 0 24px rgba(168,85,247,0.35), inset 0 0 40px rgba(168,85,247,0.06)',
    labelBg: 'linear-gradient(90deg, #a855f7, #c084fc)',
    labelText: '📣 Comunicado da Liderança',
    labelColor: '#fff',
    glow: '0 0 16px rgba(168,85,247,0.7)',
  };
  if (tipo === 'rh') return {
    border: '2px solid #f472b6',
    background: 'linear-gradient(135deg, rgba(244,114,182,0.10) 0%, rgba(244,114,182,0.03) 100%)',
    boxShadow: '0 0 18px rgba(244,114,182,0.25), inset 0 0 30px rgba(244,114,182,0.04)',
    labelBg: 'linear-gradient(90deg, #db2777, #f472b6)',
    labelText: '🧬 Comunicado do RH',
    labelColor: '#fff',
    glow: '0 0 12px rgba(244,114,182,0.5)',
  };
  if (tipo === 'admin') return {
  border: '2px solid #ff0000',
  background: 'linear-gradient(135deg, rgba(255,0,0,0.13) 0%, rgba(255,0,0,0.04) 100%)',
  boxShadow: '0 0 24px rgba(255,0,0,0.35), inset 0 0 40px rgba(255,0,0,0.06)',
  labelBg: 'linear-gradient(90deg, #cc0000, #ff4444)',
  labelText: '⚡ Comunicado Admin',
  labelColor: '#fff',
  glow: '0 0 16px rgba(255,0,0,0.7)',
};
  return null;
}

// ── Role glow helper ──────────────────────────────────────────────────────────
function getRoleStyle(role, is_rh, is_admin) {
  if (is_admin) return { color: '#ff0000', textShadow: '0 0 8px rgba(255,0,0,0.9), 0 0 16px rgba(255,0,0,0.6)', fontWeight: 700 };
  if (role === 'Diretora' || role === 'Diretor') return { color: '#ff2d7a', textShadow: '0 0 8px rgba(255,45,122,0.8)', fontWeight: 700 };
  if (role === 'Líder') return { color: '#a855f7', textShadow: '0 0 8px rgba(168,85,247,0.8)', fontWeight: 700 };
  if (is_rh) return { color: '#f472b6', textShadow: '0 0 6px rgba(244,114,182,0.7)', fontWeight: 600 };
  return { color: 'var(--gold)', fontWeight: 500 };
}

// ── Avatar helper ────────────────────────────────────────────────────────────
function Avatar({ photoUrl, initials, color, size = 36 }) {
  const bg = AV_COLORS[color] || '#C9A84C';
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', background: bg,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.33, fontWeight: 700, color: '#fff',
      flexShrink: 0, overflow: 'hidden'
    }}>
      {photoUrl
        ? <img src={api.assetUrl(photoUrl)} style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: '50%' }} alt="" onError={e => { e.target.style.display = 'none'; }} />
        : initials}
    </div>
  );
}

// ── Mini carrossel do mural ──────────────────────────────────────────────────
function MuralCarousel() {
  const [items, setItems] = useState([]);
  const [current, setCurrent] = useState(0);
  const timerRef = useRef();
  const [showDetail, setShowDetail] = useState(null);

  useEffect(() => {
    api.getMural().then(setItems).catch(() => {});
  }, []);

  useEffect(() => {
    if (items.length > 1) {
      timerRef.current = setInterval(() => setCurrent(c => (c + 1) % items.length), 5000);
      return () => clearInterval(timerRef.current);
    }
  }, [items.length]);

  if (items.length === 0) return null;

  return (
    <>
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontFamily: 'Playfair Display', fontSize: 13, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, letterSpacing: 1, textTransform: 'uppercase' }}>
          ✨ Novidades em Destaque
        </div>
        <div className="mural-container" style={{ marginBottom: 0 }}>
          {items.map((item, i) => {
            const img = item.image_url ? (item.image_url.startsWith('http') ? item.image_url : `${BASE}${item.image_url}`) : '';
            return (
              <div
                key={item.id}
                className={`mural-slide${i === current ? ' active' : ''}`}
                style={{ backgroundImage: img ? `url(${img})` : 'linear-gradient(135deg, #2A2618, #3D3220)', backgroundSize: 'cover', backgroundPosition: 'center', cursor: 'pointer' }}
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
              <button key={i} className={`mural-dot${i === current ? ' active' : ''}`}
                onClick={e => { e.stopPropagation(); setCurrent(i); clearInterval(timerRef.current); }} />
            ))}
          </div>
        </div>
      </div>

      {showDetail && (
        <div className="modal-overlay" onClick={() => setShowDetail(null)}>
          <div className="modal-card" style={{ maxWidth: 700, padding: 0, overflow: 'hidden' }} onClick={e => e.stopPropagation()}>
            <div style={{ height: 220, position: 'relative', background: '#000' }}>
              {showDetail.image_url && (
                <img src={showDetail.image_url.startsWith('http') ? showDetail.image_url : `${BASE}${showDetail.image_url}`} style={{ width: '100%', height: '100%', objectFit: 'cover', opacity: 0.7 }} alt="" onError={e => e.target.style.display = 'none'} />
              )}
              <button className="modal-close" onClick={() => setShowDetail(null)} style={{ position: 'absolute', top: 15, right: 15, background: 'rgba(0,0,0,0.5)', color: '#fff' }}>✕</button>
              <div style={{ position: 'absolute', bottom: 20, left: 24, color: '#fff' }}>
                <span className="mural-tag" style={{ marginBottom: 8, display: 'inline-block' }}>{showDetail.tag}</span>
                <h2 style={{ fontFamily: 'Playfair Display', fontSize: 22 }}>{showDetail.title}</h2>
              </div>
            </div>
            <div style={{ padding: 28, background: 'var(--surface)' }}>
              {showDetail.subtitle && <p style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 14 }}>{showDetail.subtitle}</p>}
              <div style={{ lineHeight: 1.8, color: 'var(--text)', fontSize: 14, whiteSpace: 'pre-wrap' }}>
                {showDetail.content || 'Sem conteúdo adicional.'}
              </div>
              <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
                <button className="btn-admin btn-primary" onClick={() => setShowDetail(null)}>Entendido</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── FeedPage principal ───────────────────────────────────────────────────────
export default function FeedPage({ feedType = 'feed' }) {
  const { user, allUsers, canPostNovidades, canAdmin } = useAuth();
  const toast = useToast();
  const [posts, setPosts] = useState([]);
  const [text, setText] = useState('');
  const [imageUrl, setImageUrl] = useState(null);
  const [embedUrl, setEmbedUrl] = useState('');
  const [showEmbed, setShowEmbed] = useState(false);
  const [accessLevel, setAccessLevel] = useState('all');
  const [comunicadoTipo, setComunicadoTipo] = useState('none');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [expandedComments, setExpandedComments] = useState({});
  const [commentText, setCommentText] = useState({});
  const [commentLikes, setCommentLikes] = useState({});
  const [replyingTo, setReplyingTo] = useState({});
  const [replyText, setReplyText] = useState({});
  const [showComposerEmoji, setShowComposerEmoji] = useState(false);
  const [showCommentEmoji, setShowCommentEmoji] = useState({});
  const [showReplyEmoji, setShowReplyEmoji] = useState({});
  const fileRef = useRef();
  const composerRef = useRef();

  const canPost = feedType === 'feed' || (feedType === 'novidades' && canPostNovidades);

  // Quem pode marcar comunicado
  const canMarkDiretoria = user?.role === 'Diretora' || user?.role === 'Diretor';
const canMarkLideranca = user?.role === 'Líder';
const canMarkRH = !!user?.is_rh;
const canMarkAdmin = !!user?.is_admin;
const canMarkComunicado = canMarkDiretoria || canMarkLideranca || canMarkRH || canMarkAdmin;

  useEffect(() => { loadPosts(); }, [feedType]);

  // 🔄 RECARREGAR POSTS A CADA 30 SEGUNDOS
useEffect(() => {
  if (feedType !== 'feed') return;
  
  const interval = setInterval(() => {
    loadPosts();
  }, 30000);
  
  return () => clearInterval(interval);
}, [feedType]);
  
  async function loadPosts() {
    try {
      const data = await api.getPosts(feedType);
      setPosts(data);
    } catch (err) { toast(err.message, 'error'); }
  }

  async function handleImageSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    try {
      const res = await api.uploadPostImage(file);
      setImageUrl(res.url);
      toast('Imagem carregada!', 'success');
    } catch (err) { toast(err.message, 'error'); }
    finally { setUploading(false); e.target.value = ''; }
  }

  async function publish() {
    if (!text.trim() && !imageUrl && !embedUrl.trim()) return toast('Escreva algo ou adicione uma imagem.', 'error');
    setLoading(true);
    try {
      await api.createPost({
        feed: feedType, text, image_url: imageUrl,
        embed_url: embedUrl, access_level: accessLevel,
        comunicado_tipo: comunicadoTipo !== 'none' ? comunicadoTipo : null,
      });
      setText(''); setImageUrl(null); setEmbedUrl(''); setShowEmbed(false); setComunicadoTipo('none');
      toast('Publicado!', 'success');
      loadPosts();
    } catch (err) { toast(err.message, 'error'); }
    finally { setLoading(false); }
  }

  async function handleDelete(id) {
    if (!confirm('Remover esta publicação?')) return;
    try {
      await api.deletePost(id);
      setPosts(p => p.filter(x => x.id !== id));
      toast('Publicação removida.', 'success');
    } catch (err) { toast(err.message, 'error'); }
  }

  async function handlePin(id) {
    try {
      const res = await api.pinPost(id);
      setPosts(p => p.map(x => x.id === id ? { ...x, pinned: res.pinned } : x));
    } catch (err) { toast(err.message, 'error'); }
  }

  async function handleLike(id) {
    try {
      const res = await api.likePost(id);
      setPosts(p => p.map(x => x.id === id ? { ...x, likes: res.likes } : x));
    } catch (err) { toast(err.message, 'error'); }
  }

  async function handleComment(postId) {
    const txt = commentText[postId]?.trim();
    if (!txt) return;
    try {
      const res = await api.commentPost(postId, txt);
      setPosts(p => p.map(x => x.id === postId ? { ...x, comments: res.comments } : x));
      setCommentText(c => ({ ...c, [postId]: '' }));
    } catch (err) { toast(err.message, 'error'); }
  }

  function toggleCommentLike(postId, commentId) {
    const key = `${postId}_${commentId}`;
    setCommentLikes(prev => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleReply(postId, parentComment) {
    const txt = replyText[parentComment.id]?.trim();
    if (!txt) return;
    const fullText = `↩️ @${parentComment.author_name}: ${txt}`;
    try {
      const res = await api.commentPost(postId, fullText);
      setPosts(p => p.map(x => x.id === postId ? { ...x, comments: res.comments } : x));
      setReplyText(r => ({ ...r, [parentComment.id]: '' }));
      setReplyingTo(r => ({ ...r, [parentComment.id]: false }));
    } catch (err) { toast(err.message, 'error'); }
  }

  // Detectar comunicado_tipo do post (do backend ou campo extra)
  function getPostComunicadoTipo(post) {
    return post.comunicado_tipo || null;
  }

  return (
    <div>
      {feedType === 'feed' && <MuralCarousel />}
      {feedType === 'feed' && <MoodWidget />}

      {canPost && (
        <div className="composer">
          <div className="composer-top" style={{ position: 'relative' }}>
            <Avatar photoUrl={user?.photo_url} initials={user?.initials} color={user?.color} size={38} />
            <textarea
              ref={composerRef}
              className="composer-input"
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder={feedType === 'novidades' ? 'Publicar comunicado oficial ou novidade...' : 'Compartilhe um comunicado ou novidade...'}
              rows={2}
            />
            <button
              onClick={() => setShowComposerEmoji(v => !v)}
              title="Emojis"
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 20, padding: '0 4px', alignSelf: 'center', opacity: 0.7, flexShrink: 0 }}
            >😊</button>
            {showComposerEmoji && (
              <div style={{ position: 'absolute', top: '100%', right: 0, zIndex: 50 }}>
                <EmojiPicker
                  onSelect={e => { setText(t => t + e); setShowComposerEmoji(false); composerRef.current?.focus(); }}
                  onClose={() => setShowComposerEmoji(false)}
                />
              </div>
            )}
          </div>

          {/* Tipo de comunicado */}
          {canMarkComunicado && (
            <div style={{ margin: '8px 0 4px 46px', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>Tipo:</span>
              <button onClick={() => setComunicadoTipo('none')}
                style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, border: '1px solid var(--border)', cursor: 'pointer', fontFamily: 'inherit', fontWeight: comunicadoTipo === 'none' ? 700 : 400, background: comunicadoTipo === 'none' ? 'var(--surface)' : 'transparent', color: 'var(--text)' }}>
                Normal
              </button>
              {canMarkDiretoria && (
                <button onClick={() => setComunicadoTipo(comunicadoTipo === 'diretoria' ? 'none' : 'diretoria')}
                  style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, border: '2px solid #ff2d7a', cursor: 'pointer', fontFamily: 'inherit', fontWeight: 700, background: comunicadoTipo === 'diretoria' ? 'linear-gradient(90deg,#ff2d7a,#ff6eb0)' : 'transparent', color: comunicadoTipo === 'diretoria' ? '#fff' : '#ff2d7a', boxShadow: comunicadoTipo === 'diretoria' ? '0 0 10px rgba(255,45,122,0.5)' : 'none' }}>
                  📢 Comunicado Diretoria
                </button>
              )}
              {canMarkLideranca && (
                <button onClick={() => setComunicadoTipo(comunicadoTipo === 'lideranca' ? 'none' : 'lideranca')}
                  style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, border: '2px solid #a855f7', cursor: 'pointer', fontFamily: 'inherit', fontWeight: 700, background: comunicadoTipo === 'lideranca' ? 'linear-gradient(90deg,#a855f7,#c084fc)' : 'transparent', color: comunicadoTipo === 'lideranca' ? '#fff' : '#a855f7', boxShadow: comunicadoTipo === 'lideranca' ? '0 0 10px rgba(168,85,247,0.5)' : 'none' }}>
                  📣 Comunicado Liderança
                </button>
              )}
              {canMarkRH && (
                <button onClick={() => setComunicadoTipo(comunicadoTipo === 'rh' ? 'none' : 'rh')}
                  style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, border: '2px solid #f472b6', cursor: 'pointer', fontFamily: 'inherit', fontWeight: 700, background: comunicadoTipo === 'rh' ? 'linear-gradient(90deg,#db2777,#f472b6)' : 'transparent', color: comunicadoTipo === 'rh' ? '#fff' : '#db2777', boxShadow: comunicadoTipo === 'rh' ? '0 0 10px rgba(244,114,182,0.4)' : 'none' }}>
                  🧬 Comunicado RH
                </button>
              )}
              {canMarkAdmin && (
                <button onClick={() => setComunicadoTipo(comunicadoTipo === 'admin' ? 'none' : 'admin')}
                  style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, border: '2px solid #ff0000', cursor: 'pointer', fontFamily: 'inherit', fontWeight: 700, background: comunicadoTipo === 'admin' ? 'linear-gradient(90deg,#cc0000,#ff4444)' : 'transparent', color: comunicadoTipo === 'admin' ? '#fff' : '#ff0000', boxShadow: comunicadoTipo === 'admin' ? '0 0 10px rgba(255,0,0,0.5)' : 'none' }}>
                   ⚡ Comunicado Admin
                </button>
              )}
            </div>
          )}

          {showEmbed && (
            <div style={{ margin: '0 0 12px 46px' }}>
              <input
                type="url"
                value={embedUrl}
                onChange={e => setEmbedUrl(e.target.value)}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid var(--border)', fontSize: 13, fontFamily: 'inherit', color: 'var(--text)', background: 'var(--bg)' }}
                placeholder="Cole o link do Instagram, YouTube, TikTok, X..."
              />
              <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                Suporte: YouTube, Instagram (posts públicos), X (Twitter), Spotify
              </p>
            </div>
          )}

          {imageUrl && (
            <div style={{ margin: '6px 0 12px 46px' }}>
              <img
                src={api.assetUrl(imageUrl)}
                alt="Preview"
                style={{ maxWidth: 260, maxHeight: 220, borderRadius: 10, border: '1px solid var(--border)', objectFit: 'cover', display: 'block' }}
                onError={e => { e.target.style.display = 'none'; }}
              />
              <div style={{ marginTop: 6 }}>
                <button className="btn-admin btn-secondary" style={{ padding: '6px 10px' }} onClick={() => setImageUrl(null)}>
                  Remover imagem
                </button>
              </div>
            </div>
          )}

          <div className="composer-actions">
            <label className="btn-admin btn-secondary" style={{ padding: '8px 12px', cursor: 'pointer' }}>
              {uploading ? '⏳ Enviando...' : '🖼️ Foto/Print'}
              <input type="file" accept="image/*" hidden ref={fileRef} onChange={handleImageSelect} />
            </label>
            <button className="btn-admin btn-secondary" style={{ padding: '8px 12px' }} onClick={() => setShowEmbed(!showEmbed)}>
              🔗 Embed / Link Rede Social
            </button>
            <select className="access-select" value={accessLevel} onChange={e => setAccessLevel(e.target.value)}>
              <option value="all">🌐 Todos</option>
              <option value="dourado">🟡 Mínimo Dourado</option>
              <option value="platina">⬜ Mínimo Platina</option>
              <option value="diamante">💎 Somente Diamante</option>
            </select>
            <button className="btn-post" onClick={publish} disabled={loading}>
              {loading ? 'Publicando...' : 'Publicar'}
            </button>
          </div>
        </div>
      )}

      {posts.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <p>Nenhuma publicação ainda.</p>
        </div>
      )}

      {posts.map(post => {
        const liked = post.likes?.includes(user?.key);
        const comments = post.comments || [];
        const showComments = expandedComments[post.id];
        const canManage = user?.key === post.author_key || canAdmin;
        const embedHtml = post.embed_url ? buildEmbedHtml(post.embed_url) : null;
        const comunicadoTipoPost = getPostComunicadoTipo(post);
        const comunicadoStyle = comunicadoTipoPost ? getComunicadoStyle(comunicadoTipoPost) : null;
        const roleStyle = getRoleStyle(post.author_role, post.author_is_rh, post.author_is_admin);

        return (
          <div key={post.id} className={`post-card${post.pinned ? ' pinned' : ''}`} style={comunicadoStyle ? {
            border: comunicadoStyle.border,
            background: comunicadoStyle.background,
            boxShadow: comunicadoStyle.boxShadow,
            transition: 'all 0.3s',
          } : {}}>

            {/* Banner comunicado */}
            {comunicadoStyle && (
              <div style={{
                padding: '7px 16px',
                background: comunicadoStyle.labelBg,
                fontSize: 12, fontWeight: 700,
                color: comunicadoStyle.labelColor,
                letterSpacing: 0.5,
                textShadow: comunicadoStyle.glow,
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                {comunicadoStyle.labelText}
              </div>
            )}

            {post.pinned && !comunicadoStyle && (
              <div style={{ padding: '6px 16px', background: 'rgba(201,168,76,0.08)', fontSize: 11, color: 'var(--gold)', fontWeight: 600, borderBottom: '1px solid var(--border)' }}>
                📌 Fixado
              </div>
            )}
            {post.pinned && comunicadoStyle && (
              <div style={{ padding: '4px 16px', background: 'rgba(201,168,76,0.08)', fontSize: 11, color: 'var(--gold)', fontWeight: 600 }}>
                📌 Fixado
              </div>
            )}

            <div className="post-header">
              <Avatar photoUrl={post.author_photo_url} initials={post.author_initials} color={post.author_color} size={38} />
              <div className="post-meta">
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                  <span className="post-author">{post.author_name}</span>
                  {post.author_role && (
                    <span style={{ fontSize: 11, ...roleStyle }}>
                      {post.author_role}
                    </span>
                  )}
                </div>
                <div className="post-time">{timeAgo(post.created_at)}</div>
              </div>
              {canManage && (
                <div style={{ display: 'flex', gap: 6 }}>
                  {canAdmin && (
                    <button className="btn-admin btn-secondary" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => handlePin(post.id)}>
                      {post.pinned ? '📌 Desafixar' : '📌 Fixar'}
                    </button>
                  )}
                  <button className="btn-admin btn-danger" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => handleDelete(post.id)}>
                    🗑️
                  </button>
                </div>
              )}
            </div>

            {post.text && <div className="post-body">{post.text}</div>}

            {post.image_url && (
              <div className="post-image-wrap">
                <img
                  src={api.assetUrl(post.image_url)}
                  alt=""
                  style={{ width: '100%', maxHeight: 500, objectFit: 'cover', display: 'block', background: 'var(--border)' }}
                  onError={e => { e.target.style.display = 'none'; }}
                  loading="lazy"
                />
              </div>
            )}

            {embedHtml && (
              <div className="post-embed" dangerouslySetInnerHTML={{ __html: embedHtml }} />
            )}

            <div className="post-footer">
              <button className={`btn-reaction${liked ? ' liked' : ''}`} onClick={() => handleLike(post.id)}>
                {liked ? '❤️' : '🤍'} {post.likes?.length || 0}
              </button>
              <button className="btn-reaction" onClick={() => setExpandedComments(c => ({ ...c, [post.id]: !c[post.id] }))}>
                💬 {comments.length}
              </button>
            </div>

            {showComments && (
              <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)', background: 'var(--bg)' }}>
                {comments.map(c => {
                  const likeKey = `${post.id}_${c.id}`;
                  const commentLiked = !!commentLikes[likeKey];
                  const isReplying = !!replyingTo[c.id];
                  const authorUser = allUsers?.[c.author_key];
                  const roleStyle = getRoleStyle(post.author_role, post.author_is_rh, authorUser?.is_admin);
                  const authorRole = authorUser?.role || c.author_role || '';
                  const authorIsRh = authorUser?.is_rh || false;
                  const cRoleStyle = getRoleStyle(authorRole, authorIsRh);

                  return (
                    <div key={c.id} style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'flex-start' }}>
                      <Avatar photoUrl={c.author_photo_url} initials={c.author_initials} color={c.author_color} size={30} />
                      <div style={{ flex: 1 }}>
                        <div style={{ background: 'var(--surface)', borderRadius: 12, padding: '8px 12px', border: '1px solid var(--border)' }}>
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 2, flexWrap: 'wrap' }}>
                            <span style={{ fontSize: 13, fontWeight: 700 }}>{c.author_name}</span>
                            {authorRole && (
                              <span style={{ fontSize: 11, ...cRoleStyle }}>{authorRole}</span>
                            )}
                          </div>
                          <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.5 }}>{c.text}</div>
                        </div>

                        <div style={{ display: 'flex', gap: 14, marginTop: 4, paddingLeft: 4 }}>
                          <button
                            onClick={() => toggleCommentLike(post.id, c.id)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12,
                              color: commentLiked ? '#ff4d6d' : 'var(--text-muted)', fontFamily: 'inherit',
                              display: 'flex', alignItems: 'center', gap: 3, padding: 0 }}
                          >
                            {commentLiked ? '❤️' : '🤍'} Curtir
                          </button>
                          <button
                            onClick={() => setReplyingTo(r => ({ ...r, [c.id]: !r[c.id] }))}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12,
                              color: isReplying ? 'var(--gold)' : 'var(--text-muted)', fontFamily: 'inherit', padding: 0 }}
                          >
                            ↩️ Responder
                          </button>
                        </div>

                        {isReplying && (
                          <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center', position: 'relative' }}>
                            <Avatar photoUrl={user?.photo_url} initials={user?.initials} color={user?.color} size={22} />
                            <div style={{ flex: 1, position: 'relative' }}>
                              <input
                                autoFocus
                                value={replyText[c.id] || ''}
                                onChange={e => setReplyText(r => ({ ...r, [c.id]: e.target.value }))}
                                onKeyDown={e => e.key === 'Enter' && handleReply(post.id, c)}
                                placeholder={`Responder ${c.author_name}...`}
                                style={{ width: '100%', padding: '5px 32px 5px 10px', borderRadius: 16, border: '1.5px solid var(--border)',
                                  fontSize: 12, fontFamily: 'inherit', background: 'var(--surface)', color: 'var(--text)', boxSizing: 'border-box' }}
                              />
                              <button onClick={() => setShowReplyEmoji(r => ({ ...r, [c.id]: !r[c.id] }))}
                                style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, opacity: 0.6 }}>😊</button>
                              {showReplyEmoji[c.id] && (
                                <EmojiPicker
                                  onSelect={e => { setReplyText(r => ({ ...r, [c.id]: (r[c.id] || '') + e })); setShowReplyEmoji(r => ({ ...r, [c.id]: false })); }}
                                  onClose={() => setShowReplyEmoji(r => ({ ...r, [c.id]: false }))}
                                />
                              )}
                            </div>
                            <button
                              onClick={() => handleReply(post.id, c)}
                              style={{ background: 'var(--gold)', color: '#fff', border: 'none', borderRadius: 12,
                                padding: '5px 10px', fontSize: 12, cursor: 'pointer', fontFamily: 'inherit' }}
                            >Enviar</button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Campo comentário com emoji */}
                <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center', position: 'relative' }}>
                  <Avatar photoUrl={user?.photo_url} initials={user?.initials} color={user?.color} size={28} />
                  <div style={{ flex: 1, position: 'relative' }}>
                    <input
                      type="text"
                      value={commentText[post.id] || ''}
                      onChange={e => setCommentText(c => ({ ...c, [post.id]: e.target.value }))}
                      onKeyDown={e => e.key === 'Enter' && handleComment(post.id)}
                      placeholder="Comentar..."
                      style={{ width: '100%', padding: '7px 36px 7px 12px', borderRadius: 20, border: '1.5px solid var(--border)', fontSize: 13, fontFamily: 'inherit', background: 'var(--surface)', color: 'var(--text)', boxSizing: 'border-box' }}
                    />
                    <button onClick={() => setShowCommentEmoji(s => ({ ...s, [post.id]: !s[post.id] }))}
                      style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, opacity: 0.6 }}>😊</button>
                    {showCommentEmoji[post.id] && (
                      <EmojiPicker
                        onSelect={e => { setCommentText(c => ({ ...c, [post.id]: (c[post.id] || '') + e })); setShowCommentEmoji(s => ({ ...s, [post.id]: false })); }}
                        onClose={() => setShowCommentEmoji(s => ({ ...s, [post.id]: false }))}
                      />
                    )}
                  </div>
                  <button className="btn-post" style={{ padding: '7px 14px' }} onClick={() => handleComment(post.id)}>Enviar</button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
