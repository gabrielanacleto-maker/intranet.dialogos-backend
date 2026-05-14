import { useAuth } from '../context/AuthContext';
import FeedPage from './FeedPage';

function canPostInternal(user) {
  if (!user) return false;
  const role = (user.role || '').toLowerCase();
  return (
    user.is_admin || user.is_admin_user ||
    user.is_rh ||
    user.is_diretor || user.is_leader ||
    role === 'admin' || role === 'diretora' || role === 'diretor' ||
    role === 'líder' || role === 'lider' || role === 'rh'
  );
}

export default function ComunicadoInterno() {
  const { user } = useAuth();

  return (
    <div>
      {/* Interna header */}
      <div className="surface-card" style={{
        padding: '24px 28px', marginBottom: 20, borderRadius: 16,
        background: 'linear-gradient(135deg, rgba(201,168,76,0.10) 0%, rgba(201,168,76,0.03) 100%)',
        border: '1px solid rgba(201,168,76,0.15)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
          <span style={{ fontSize: 24 }}>📢</span>
          <h2 style={{ fontFamily: 'Playfair Display', fontSize: 20, fontWeight: 700, margin: 0 }}>
            Comunicados Internos
          </h2>
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
          Canal oficial para comunicados administrativos e institucionais
        </p>
        {!canPostInternal(user) && (
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 10, fontStyle: 'italic' }}>
            Apenas líderes, RH, diretores e administradores podem publicar comunicados internos.
            Todos podem visualizar, comentar e curtir.
          </p>
        )}
      </div>

      <FeedPage feedType="internal" canPostOverride={canPostInternal(user)} />
    </div>
  );
}