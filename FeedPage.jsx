import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { gamificacao } from '../services/gamificacao';
import { AV_COLORS } from '../utils';

export default function FeedPage({ feedType = 'feed' }) {
  const { user } = useAuth();
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newPostText, setNewPostText] = useState('');
  const [newPostFile, setNewPostFile] = useState(null);
  const [submittingPost, setSubmittingPost] = useState(false);
  const [expandedComments, setExpandedComments] = useState({});

  // Carregar posts
  useEffect(() => {
    fetchPosts();
  }, [feedType]);

  async function fetchPosts() {
    setLoading(true);
    try {
      const endpoint = feedType === 'novidades' ? '/api/posts/novidades' : '/api/posts';
      const data = await api.get(endpoint);
      setPosts(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Erro ao carregar posts:', err);
      setPosts([]);
    } finally {
      setLoading(false);
    }
  }

  async function createPost() {
    if (!newPostText.trim()) {
      alert('Escreva algo!');
      return;
    }

    setSubmittingPost(true);
    try {
      const formData = new FormData();
      formData.append('content', newPostText);
      if (newPostFile) formData.append('file', newPostFile);

      const response = await api.post('/api/posts', formData);
      setNewPostText('');
      setNewPostFile(null);

      // ⭐ ADICIONAR PONTOS AUTOMATICAMENTE AO POSTAR
      try {
        await gamificacao.addPoints(user.key, 10, 'Criou um novo post');
        console.log('✅ +10 pontos por criar post');
      } catch (err) {
        console.warn('Aviso: Não foi possível adicionar pontos:', err.message);
      }

      await fetchPosts();
    } catch (err) {
      alert(err.message);
    } finally {
      setSubmittingPost(false);
    }
  }

  async function likePost(postId) {
    try {
      const post = posts.find(p => p.id === postId);
      if (!post) return;

      const isLiked = post.likes.some(l => l.user_key === user.key);

      if (isLiked) {
        await api.delete(`/api/posts/${postId}/like`);
      } else {
        await api.post(`/api/posts/${postId}/like`);
        
        // ⭐ ADICIONAR 1 PONTO AUTOMATICAMENTE AO CURTIR
        try {
          await gamificacao.addPoints(user.key, 1, 'Curtiu um post');
          console.log('✅ +1 ponto por curtir');
        } catch (err) {
          console.warn('Aviso: Não foi possível adicionar ponto:', err.message);
        }
      }

      await fetchPosts();
    } catch (err) {
      console.error('Erro ao curtir:', err);
    }
  }

  async function addComment(postId, text) {
    if (!text.trim()) return;

    try {
      await api.post(`/api/posts/${postId}/comments`, { content: text });

      // ⭐ ADICIONAR 5 PONTOS AUTOMATICAMENTE AO COMENTAR
      try {
        await gamificacao.addPoints(user.key, 5, 'Fez um comentário');
        console.log('✅ +5 pontos por comentar');
      } catch (err) {
        console.warn('Aviso: Não foi possível adicionar pontos:', err.message);
      }

      await fetchPosts();
      setExpandedComments(prev => ({ ...prev, [postId]: false }));
    } catch (err) {
      console.error('Erro ao comentar:', err);
    }
  }

  async function deletePost(postId) {
    if (!confirm('Tem certeza?')) return;
    try {
      await api.delete(`/api/posts/${postId}`);
      await fetchPosts();
    } catch (err) {
      alert(err.message);
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: 24, animation: 'spin 1s linear infinite', marginBottom: 12 }}>⏳</div>
        Carregando posts...
      </div>
    );
  }

  return (
    <div className="feed-container">
      {/* Criar Post */}
      <div className="post-card">
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <div
            className="avatar-sm"
            style={{
              background: AV_COLORS[user.color] || '#C9A84C',
              width: 44,
              height: 44,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            {user.initials}
          </div>
          <div style={{ flex: 1 }}>
            <textarea
              className="post-textarea"
              placeholder="O que você está pensando? 💭"
              value={newPostText}
              onChange={e => setNewPostText(e.target.value)}
              style={{
                width: '100%',
                minHeight: 100,
                padding: 12,
                borderRadius: 8,
                border: '1px solid var(--border)',
                backgroundColor: 'var(--bg-secondary)',
                color: 'var(--text)',
                fontFamily: 'inherit',
                fontSize: 14,
                resize: 'vertical',
              }}
            />
            <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
              <label style={{ cursor: 'pointer', color: 'var(--gold)', fontSize: 14, fontWeight: 500 }}>
                📎 Arquivo
                <input
                  type="file"
                  hidden
                  onChange={e => setNewPostFile(e.target.files?.[0] || null)}
                />
              </label>
              {newPostFile && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>✅ {newPostFile.name}</span>}
              <button
                onClick={createPost}
                disabled={submittingPost || !newPostText.trim()}
                style={{
                  marginLeft: 'auto',
                  padding: '8px 16px',
                  background: 'var(--gold)',
                  color: '#000',
                  border: 'none',
                  borderRadius: 6,
                  fontWeight: 600,
                  cursor: submittingPost ? 'not-allowed' : 'pointer',
                  opacity: submittingPost || !newPostText.trim() ? 0.5 : 1,
                }}
              >
                {submittingPost ? 'Postando...' : 'Postar'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Lista de Posts */}
      {posts.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
          <p style={{ fontSize: 14 }}>Nenhum post ainda. Seja o primeiro a compartilhar! 🚀</p>
        </div>
      ) : (
        posts.map(post => (
          <div key={post.id} className="post-card">
            {/* Header do Post */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flex: 1 }}>
                <div
                  className="avatar-sm"
                  style={{
                    background: AV_COLORS[post.author_color] || '#C9A84C',
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff',
                    fontWeight: 600,
                    flexShrink: 0,
                  }}
                >
                  {post.author_initials}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <strong style={{ color: 'var(--text)' }}>{post.author_name}</strong>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{post.author_role}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {new Date(post.created_at).toLocaleDateString('pt-BR')} às {new Date(post.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
              </div>
              {post.author_key === user.key && (
                <button
                  onClick={() => deletePost(post.id)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 18,
                    padding: 0,
                  }}
                  title="Deletar post"
                >
                  🗑️
                </button>
              )}
            </div>

            {/* Conteúdo */}
            <div style={{ marginBottom: 12, color: 'var(--text)', lineHeight: 1.6 }}>{post.content}</div>

            {/* Arquivo */}
            {post.file_url && (
              <div style={{ marginBottom: 12 }}>
                <a
                  href={api.assetUrl(post.file_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    color: 'var(--gold)',
                    textDecoration: 'none',
                    fontSize: 13,
                    fontWeight: 500,
                  }}
                >
                  📎 {post.file_url.split('/').pop()}
                </a>
              </div>
            )}

            {/* Ações */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
              <button
                onClick={() => likePost(post.id)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 13,
                  color: post.likes.some(l => l.user_key === user.key) ? 'var(--gold)' : 'var(--text-muted)',
                  fontWeight: 500,
                }}
              >
                ❤️ {post.likes.length} Curtir
              </button>
              <button
                onClick={() => setExpandedComments(prev => ({ ...prev, [post.id]: !prev[post.id] }))}
                style={{
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 13,
                  color: 'var(--text-muted)',
                  fontWeight: 500,
                }}
              >
                💬 {post.comments.length} Comentar
              </button>
            </div>

            {/* Comentários */}
            {expandedComments[post.id] && (
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                {post.comments.map(comment => (
                  <div key={comment.id} style={{ marginBottom: 10, fontSize: 13 }}>
                    <div style={{ fontWeight: 600, color: 'var(--text)' }}>{comment.author_name}</div>
                    <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>
                      {new Date(comment.created_at).toLocaleDateString('pt-BR')} {new Date(comment.created_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}
                    </div>
                    <div style={{ color: 'var(--text)', marginBottom: 8 }}>{comment.content}</div>
                  </div>
                ))}

                {/* Input de Comentário */}
                <CommentInput onSubmit={text => addComment(post.id, text)} />
              </div>
            )}
          </div>
        ))
      )}

      <style>{`
        .feed-container {
          max-width: 600px;
          margin: 0 auto;
          padding: 20px;
        }

        .post-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 16px;
          margin-bottom: 16px;
          transition: all 0.2s ease;
        }

        .post-card:hover {
          border-color: var(--gold);
          box-shadow: 0 2px 8px rgba(201, 168, 76, 0.1);
        }
      `}</style>
    </div>
  );
}

function CommentInput({ onSubmit }) {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    if (!text.trim()) return;
    setLoading(true);
    await onSubmit(text);
    setText('');
    setLoading(false);
  }

  return (
    <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
      <input
        type="text"
        placeholder="Escreva um comentário..."
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && handleSubmit()}
        style={{
          flex: 1,
          padding: '8px 12px',
          borderRadius: 6,
          border: '1px solid var(--border)',
          backgroundColor: 'var(--bg)',
          color: 'var(--text)',
          fontSize: 13,
        }}
      />
      <button
        onClick={handleSubmit}
        disabled={loading || !text.trim()}
        style={{
          padding: '8px 12px',
          background: 'var(--gold)',
          color: '#000',
          border: 'none',
          borderRadius: 6,
          fontWeight: 600,
          cursor: loading ? 'not-allowed' : 'pointer',
          opacity: loading || !text.trim() ? 0.5 : 1,
        }}
      >
        {loading ? '...' : '📤'}
      </button>
    </div>
  );
}
