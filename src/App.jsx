import { useState, useEffect } from 'react';
import { useAuth } from './context/AuthContext';
import LoginPage from './pages/LoginPage';
import ChangePasswordPage from './pages/ChangePasswordPage';
import FeedPage from './pages/FeedPage';
import NovidadesPage from './pages/NovidadesPage';
import DocsPage from './pages/DocsPage';
import ProfilePage from './pages/ProfilePage';
import AdminPage from './pages/AdminPage';
import CursorGlow from './components/CursorGlow';
import Equipe from './pages/Equipe';
import OuvidoriaPage from './pages/OuvidoriaPage';
import TeamWidget from './components/TeamWidget';
import { api } from './services/api';
import { AV_COLORS, LEVEL_LABEL, LEVEL_BADGE_CLASS, CURSOR_OPTIONS, getTenureLabel, getTenureClass, getRoleGlowClass, getRoleStyle } from './utils';
import CalendarioPage from './pages/CalendarioPage';
import SalaPage from './pages/SalaPage';

export default function App() {
  const { user, mustChangePassword, logout, canSeeNovidades, canAdmin } = useAuth();
  const [page, setPage] = useState('feed');
  const [darkMode, setDarkMode] = useState(() => localStorage.getItem('dialogos_theme') === 'dark');
  document.body.style.background = 'blue';
  alert('APP RAIZ');
  
  // Apply theme
  useEffect(() => {
    document.body.classList.toggle('dark-theme', darkMode);
    localStorage.setItem('dialogos_theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  // Restore cursor preference
  useEffect(() => {
    const saved = localStorage.getItem('dialogos_cursor') || 'normal';
    CURSOR_OPTIONS.forEach(c => document.body.classList.remove(`cursor-${c.key}`));
    document.body.classList.add(`cursor-${saved}`);
  }, [user]);

  if (!user) return <><LoginPage /><CursorGlow /></>;
  if (mustChangePassword) return <><ChangePasswordPage /><CursorGlow /></>;

  const avatarBg = AV_COLORS[user.color] || '#C9A84C';
  const photoUrl = user.photo_url ? api.assetUrl(user.photo_url) : localStorage.getItem('profilePhoto_' + user.key);
  const roleStyle = getRoleStyle(user.role, user.is_rh, user.is_admin);

  const navItems = [
    { key: 'novidades', label: 'Feed Novidades Diálogos', icon: '✨', show: canSeeNovidades, highlight: true },
    { key: 'feed', label: 'Feed Diálogos', icon: '📋', show: true },
    { key: 'sala', label: 'Sala', icon: '💬', show: true },
    { key: 'myprofile', label: 'Meu Perfil', icon: '👤', show: true },
    { key: 'calendario', label: 'Calendário', icon: '📅', show: true },
    { key: 'docs', label: 'Documentações', icon: '📁', show: true },
    { key: 'team', label: 'Equipe', icon: '👥', show: true },
    { key: 'ouvidoria', label: 'Ouvidoria', icon: '📢', show: true },
  ];

  const adminItems = [
    { key: 'admin', label: 'Configurações', icon: '⚙️', show: canAdmin },
  ];

  function renderPage() {
    switch (page) {
      case 'feed': return <FeedPage feedType="feed" />;
      case 'novidades': return <NovidadesPage />;
      case 'docs': return <DocsPage />;
      case 'myprofile': return <ProfilePage />;
      case 'admin': return <AdminPage />;
      case 'team': return <Equipe />;
      case 'ouvidoria': return <OuvidoriaPage />;
      case 'calendario': return <CalendarioPage />;
      case 'sala': return <SalaPage />;
      default: return (
        <div style={{ textAlign: 'center', padding: '80px 20px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🚧</div>
          <p style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>Em construção</p>
          <p style={{ fontSize: 13 }}>Esta seção ainda está sendo desenvolvida.</p>
        </div>
      );
    }
  }

  return (
    <>
      <CursorGlow />
      <div className="app-layout">
        {/* TOPBAR */}
        <header className="topbar">
          <div className="topbar-logo">
            <img
              src="/logo-clinica-fivecon.ico"
              alt="Logo Clínica Diálogos"
              style={{ width: 40, height: 40, objectFit: 'contain' }}
              />
            <div>
              <small>Clínica</small>
              <span>Diálogos</span>
            </div>
          </div>

          <div className="topbar-search">
            <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: 14 }}>🔍</span>
            <input type="text" placeholder="Buscar na intranet..." />
          </div>

          <div className="topbar-actions">
            <div className="topbar-icon" onClick={() => setDarkMode(d => !d)} title="Alternar tema">
              {darkMode ? '🌙' : '☀️'}
            </div>
            <div className="topbar-icon" title="Notificações">🔔</div>
            <div
              className="topbar-avatar"
              onClick={() => setPage('myprofile')}
              title="Meu Perfil"
              style={{ overflow: 'hidden', background: photoUrl ? 'transparent' : avatarBg }}
            >
              {photoUrl
                ? <img src={photoUrl} style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} alt="" onError={e => e.target.style.display='none'} />
                : user.initials?.[0]}
            </div>
          </div>
        </header>

        {/* SIDEBAR */}
        <aside className="sidebar">
          <div className="profile-card">
            <div className="profile-photo-container">
              <div className="profile-photo-ring">
                {photoUrl
                  ? <img src={photoUrl} className="profile-photo" alt={user.name} onError={e => e.target.style.display='none'} />
                  : <span className="profile-photo-initials">{user.initials}</span>}
              </div>
              <label className="change-photo-btn" htmlFor="sidebar-photo-upload">Alterar Foto</label>
              <input type="file" id="sidebar-photo-upload" accept="image/*" hidden onChange={async e => {
                const file = e.target.files[0];
                if (!file) return;
                try {
                  const res = await api.uploadPhoto(file);
                  localStorage.setItem('profilePhoto_' + user.key, api.assetUrl(res.url));
                  window.location.reload();
                } catch (err) { alert(err.message); }
                e.target.value = '';
              }} />
            </div>
            <div className="profile-name">{user.name}</div>
            <div className={`profile-role ${getRoleGlowClass(user.role, user.dept)}`} style={roleStyle}>{user.role}</div>
            <div className="profile-dept">{user.dept}</div>
            <div className="badges-row">
              <span className={`access-badge ${LEVEL_BADGE_CLASS[user.level] || 'badge-dourado'}`}>{LEVEL_LABEL[user.level]}</span>
              {!!user.is_rh && <span className="access-badge badge-rh">🧬 RH</span>}
              {!!user.is_ouvidor && <span className="access-badge badge-ouvidor">👁️ Ouvidor</span>}
              {!!user.is_admin_user && !user.is_admin && <span className="access-badge badge-admin-user">🛡️ Admin User</span>}
              {!!user.is_admin && <span className="access-badge badge-super-admin">⚡ Admin System</span>}
              {!!user.is_orcoma && <span className="access-badge badge-orcoma">🔷 Orcoma</span>}
            </div>
            {getTenureLabel(user.hire_date) && (
              <div className={`tenure-badge ${getTenureClass(user.hire_date)}`} style={{ marginTop: 6 }}>
                {getTenureLabel(user.hire_date)}
              </div>
            )}
          </div>

          <div className="nav-section-label">Menu</div>
          {navItems.filter(n => n.show).map(n => (
            <div key={n.key}
              className={`nav-item${page === n.key ? ' active' : ''}`}
              onClick={() => setPage(n.key)}
              style={n.highlight && page !== n.key ? { color: 'var(--gold)', fontWeight: 600 } : {}}
            >
              <span className="nav-icon">{n.icon}</span>
              {n.label}
            </div>
          ))}

          {adminItems.some(a => a.show) && (
            <>
              <div className="nav-section-label">Admin</div>
              {adminItems.filter(a => a.show).map(a => (
                <div key={a.key} className={`nav-item${page === a.key ? ' active' : ''}`} onClick={() => setPage(a.key)}>
                  <span className="nav-icon">{a.icon}</span>
                  {a.label}
                </div>
              ))}
            </>
          )}

          <div style={{ marginTop: 20 }}>
            <div className="nav-item" onClick={logout}>
              <span className="nav-icon">🚪</span> Sair
            </div>
          </div>
        </aside>

        {/* MAIN */}
        <main className="main">
          {renderPage()}
        </main>

        {/* RIGHT PANEL */}
        <aside className="right-panel">
          <div className="widget">
            <div className="widget-title">📅 Data de Hoje</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {new Date().toLocaleDateString('pt-BR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
            </div>
          </div>
          <div className="widget">
            <div className="widget-title">🎭 Cursor Ativo</div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              {CURSOR_OPTIONS.find(c => c.key === (localStorage.getItem('dialogos_cursor') || 'normal'))?.label || 'Normal'}
            </div>
            <button className="btn-admin btn-secondary" style={{ padding: '5px 10px', fontSize: 11, marginTop: 8 }} onClick={() => setPage('myprofile')}>
              Mudar cursor →
            </button>
          </div>
          <TeamWidget />
        </aside>
      </div>
    </>
  );
}
