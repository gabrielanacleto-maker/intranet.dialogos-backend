import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { api } from '../services/api';
import { AV_COLORS, LEVEL_LABEL, LEVEL_BADGE_CLASS, getRoleGlowClass, getRoleStyle, getTenureLabel, getTenureClass } from '../utils';
import MoodReport from '../components/MoodReport';

const MOODS = [
  { emoji: '😄', label: 'Feliz', value: 'happy', color: '#FFD700' },
  { emoji: '😊', label: 'Bem', value: 'good', color: '#90EE90' },
  { emoji: '😐', label: 'Neutro', value: 'neutral', color: '#87CEEB' },
  { emoji: '😕', label: 'Triste', value: 'sad', color: '#FF6B6B' },
  { emoji: '😤', label: 'Frustrado', value: 'frustrated', color: '#FF4500' },
];

export default function ProfilePage() {
  const { user } = useAuth();
  const [profilePhoto, setProfilePhoto] = useState(null);
  const [userPoints, setUserPoints] = useState(0);
  const [pointsHistory, setPointsHistory] = useState([]);
  const [moods, setMoods] = useState([]);
  const [selectedMood, setSelectedMood] = useState(null);
  const [moodSubmitting, setMoodSubmitting] = useState(false);
  const [showMoodChart, setShowMoodChart] = useState(false);
  const [loadingPoints, setLoadingPoints] = useState(true);
  const [loadingMoods, setLoadingMoods] = useState(true);

  const avatarBg = AV_COLORS[user.color] || '#C9A84C';
  const photoUrl = user.photo_url ? api.assetUrl(user.photo_url) : localStorage.getItem('profilePhoto_' + user.key);
  const roleStyle = getRoleStyle(user.role, user.is_rh, user.is_admin);

  // Carregar pontos
  useEffect(() => {
    fetchUserPoints();
  }, []);

  // Carregar moods
  useEffect(() => {
    fetchUserMoods();
  }, []);

  async function fetchUserPoints() {
    try {
      setLoadingPoints(true);
      const data = await gamificacao.getUserPoints(user.key);
      setUserPoints(data.total || 0);
      setPointsHistory(data.history || []);
    } catch (err) {
      console.error('Erro ao carregar pontos:', err);
      setUserPoints(0);
      setPointsHistory([]);
    } finally {
      setLoadingPoints(false);
    }
  }

  async function fetchUserMoods() {
    try {
      setLoadingMoods(true);
      const data = await api.get(`/api/moods/user/${user.key}`);
      setMoods(data.moods || []);
    } catch (err) {
      console.error('Erro ao carregar moods:', err);
      setMoods([]);
    } finally {
      setLoadingMoods(false);
    }
  }

  async function submitMood(moodValue) {
    setMoodSubmitting(true);
    try {
      await api.post('/api/moods', { user_key: user.key, mood: moodValue });
      setSelectedMood(moodValue);
      setTimeout(() => setSelectedMood(null), 3000);
      await fetchUserMoods();
    } catch (err) {
      console.error('Erro ao salvar mood:', err);
    } finally {
      setMoodSubmitting(false);
    }
  }

  function handlePhotoUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const photoData = event.target.result;
      localStorage.setItem('profilePhoto_' + user.key, photoData);
      setProfilePhoto(photoData);
      window.location.reload();
    };
    reader.readAsDataURL(file);
  }

  const moodStats = {
    happy: moods.filter(m => m.mood === 'happy').length,
    good: moods.filter(m => m.mood === 'good').length,
    neutral: moods.filter(m => m.mood === 'neutral').length,
    sad: moods.filter(m => m.mood === 'sad').length,
    frustrated: moods.filter(m => m.mood === 'frustrated').length,
  };

  const totalMoods = Object.values(moodStats).reduce((a, b) => a + b, 0);

  return (
    <div className="profile-page">
      <style>{`
        .profile-page {
          max-width: 900px;
          margin: 0 auto;
          padding: 20px;
        }

        .profile-card-large {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 20px;
          padding: 40px;
          margin-bottom: 30px;
          text-align: center;
        }

        .profile-photo-large {
          width: 120px;
          height: 120px;
          border-radius: 50%;
          margin: 0 auto 20px;
          object-fit: cover;
          border: 3px solid var(--gold);
          box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
        }

        .photo-upload-label {
          display: inline-block;
          margin-top: 15px;
          padding: 10px 20px;
          background: var(--gold);
          color: #000;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          font-weight: 600;
          font-size: 13px;
          transition: all 0.2s;
        }

        .photo-upload-label:hover {
          transform: scale(1.05);
          box-shadow: 0 4px 15px rgba(201, 168, 76, 0.3);
        }

        .profile-name-large {
          font-size: 28px;
          font-weight: 800;
          color: var(--text);
          margin: 10px 0 5px 0;
        }

        .profile-role-large {
          font-size: 16px;
          font-weight: 600;
          margin-bottom: 5px;
        }

        .profile-dept-large {
          font-size: 14px;
          color: var(--text-muted);
          margin-bottom: 20px;
        }

        .badges-grid {
          display: flex;
          flex-wrap: wrap;
          justify-content: center;
          gap: 10px;
          margin-bottom: 30px;
        }

        .badge {
          padding: 8px 16px;
          border-radius: 20px;
          font-size: 12px;
          font-weight: 600;
          border: 1px solid var(--border);
          background: var(--bg);
        }

        .badge.badge-dourado {
          background: rgba(201, 168, 76, 0.1);
          border-color: var(--gold);
          color: var(--gold);
        }

        .badge.badge-diamante {
          background: rgba(100, 200, 255, 0.1);
          border-color: #64C8FF;
          color: #64C8FF;
        }

        .badge.badge-prata {
          background: rgba(192, 192, 192, 0.1);
          border-color: #C0C0C0;
          color: #C0C0C0;
        }

        .points-section {
          background: linear-gradient(135deg, rgba(201, 168, 76, 0.1) 0%, rgba(201, 168, 76, 0.05) 100%);
          border: 1px solid rgba(201, 168, 76, 0.3);
          border-radius: 15px;
          padding: 20px;
          margin-bottom: 30px;
          text-align: center;
        }

        .points-number {
          font-size: 48px;
          font-weight: 800;
          color: var(--gold);
          margin: 0;
        }

        .points-label {
          font-size: 14px;
          color: var(--text-muted);
          margin-top: 5px;
        }

        .mood-section {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 20px;
          padding: 30px;
          margin-bottom: 30px;
        }

        .section-title {
          font-size: 20px;
          font-weight: 700;
          color: var(--text);
          margin: 0 0 20px 0;
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .mood-selector {
          display: flex;
          justify-content: center;
          gap: 15px;
          flex-wrap: wrap;
          margin-bottom: 20px;
        }

        .mood-button {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
          padding: 15px 20px;
          background: var(--bg);
          border: 2px solid var(--border);
          border-radius: 15px;
          cursor: pointer;
          transition: all 0.3s;
          font-size: 13px;
          font-weight: 600;
          color: var(--text-muted);
        }

        .mood-button:hover {
          border-color: var(--gold);
          transform: translateY(-4px);
          box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
        }

        .mood-emoji {
          font-size: 32px;
          display: block;
          line-height: 1;
        }

        .mood-button.selected {
          border-color: var(--gold);
          background: rgba(201, 168, 76, 0.1);
          color: var(--gold);
        }

        .mood-success {
          display: flex;
          align-items: center;
          gap: 10px;
          color: #4CAF50;
          font-weight: 600;
          padding: 12px;
          background: rgba(76, 175, 80, 0.1);
          border-radius: 8px;
          margin-bottom: 15px;
        }

        .mood-chart {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: 15px;
          margin-top: 20px;
        }

        .mood-stat {
          background: var(--bg);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 15px;
          text-align: center;
        }

        .mood-stat-emoji {
          font-size: 32px;
          display: block;
          margin-bottom: 8px;
        }

        .mood-stat-count {
          font-size: 24px;
          font-weight: 800;
          color: var(--gold);
          margin-bottom: 5px;
        }

        .mood-stat-label {
          font-size: 12px;
          color: var(--text-muted);
        }

        .mood-chart-toggle {
          display: inline-block;
          margin-top: 15px;
          padding: 8px 16px;
          background: transparent;
          border: 1px solid var(--border);
          border-radius: 8px;
          color: var(--text);
          cursor: pointer;
          font-weight: 600;
          transition: all 0.2s;
        }

        .mood-chart-toggle:hover {
          border-color: var(--gold);
          color: var(--gold);
        }

        .info-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 20px;
          margin-bottom: 30px;
        }

        .info-card {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 15px;
          padding: 20px;
        }

        .info-label {
          font-size: 12px;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 8px;
        }

        .info-value {
          font-size: 18px;
          font-weight: 700;
          color: var(--text);
        }

        .points-history {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          border-radius: 15px;
          padding: 20px;
        }

        .history-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px;
          border-bottom: 1px solid var(--border);
          font-size: 13px;
        }

        .history-item:last-child {
          border-bottom: none;
        }

        .history-reason {
          color: var(--text-muted);
        }

        .history-points {
          color: var(--gold);
          font-weight: 700;
        }

        .loading {
          color: var(--text-muted);
          font-style: italic;
        }
      `}</style>

      {/* CARD PRINCIPAL */}
      <div className="profile-card-large">
        {photoUrl ? (
          <img src={photoUrl} alt={user.name} className="profile-photo-large" />
        ) : (
          <div
            className="profile-photo-large"
            style={{
              background: avatarBg,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: 40,
              fontWeight: 800,
            }}
          >
            {user.initials}
          </div>
        )}

        <label className="photo-upload-label">
          📷 Alterar Foto
          <input type="file" hidden accept="image/*" onChange={handlePhotoUpload} />
        </label>

        <div className="profile-name-large">{user.name}</div>
        <div className="profile-role-large" style={roleStyle}>
          {user.role}
        </div>
        <div className="profile-dept-large">{user.dept}</div>

        <div className="badges-grid">
          <span className={`badge ${LEVEL_BADGE_CLASS[user.level] || 'badge-dourado'}`}>
            {LEVEL_LABEL[user.level]}
          </span>
          {user.is_rh && <span className="badge badge-diamante">🧬 RH</span>}
          {user.is_ouvidor && <span className="badge">👁️ Ouvidor</span>}
          {user.is_admin_user && !user.is_admin && <span className="badge">🛡️ Admin User</span>}
          {user.is_admin && <span className="badge badge-prata">⚡ Admin System</span>}
        </div>

        {getTenureLabel(user.hire_date) && (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
            🎉 {getTenureLabel(user.hire_date)}
          </div>
        )}
      </div>

      {/* PONTOS */}
      {loadingPoints ? (
        <div className="points-section">
          <div className="loading">Carregando pontos...</div>
        </div>
      ) : (
        <div className="points-section">
          <div className="points-number">⭐ {userPoints}</div>
          <div className="points-label">PONTOS ACUMULADOS</div>
        </div>
      )}

      {/* HISTÓRICO DE PONTOS */}
      {pointsHistory.length > 0 && (
        <div className="points-history">
          <h3 className="section-title">📊 Histórico de Pontos</h3>
          {pointsHistory.map((item, idx) => (
            <div key={idx} className="history-item">
              <div className="history-reason">{item.reason}</div>
              <div className="history-points">+{item.points}</div>
            </div>
          ))}
        </div>
      )}

      {/* MOOD SELECTOR */}
      <div className="mood-section">
        <h3 className="section-title">😄 Como você está se sentindo hoje?</h3>

        {selectedMood && (
          <div className="mood-success">
            ✅ Seu sentimento foi registrado!
          </div>
        )}

        <div className="mood-selector">
          {MOODS.map(mood => (
            <button
              key={mood.value}
              className={`mood-button${selectedMood === mood.value ? ' selected' : ''}`}
              onClick={() => submitMood(mood.value)}
              disabled={moodSubmitting}
              style={selectedMood === mood.value ? { borderColor: mood.color, color: mood.color } : {}}
            >
              <span className="mood-emoji">{mood.emoji}</span>
              {mood.label}
            </button>
          ))}
        </div>

        {totalMoods > 0 && (
          <>
            <button className="mood-chart-toggle" onClick={() => setShowMoodChart(!showMoodChart)}>
              {showMoodChart ? '📉 Esconder Relatório' : '📈 Ver Relatório'}
            </button>

            {showMoodChart && (
              <div className="mood-chart">
                {MOODS.map(mood => {
                  const moodEmoji = mood.emoji;
                  const count = moodStats[mood.value];
                  const percentage = totalMoods > 0 ? Math.round((count / totalMoods) * 100) : 0;

                  return (
                    <div key={mood.value} className="mood-stat">
                      <span className="mood-stat-emoji">{moodEmoji}</span>
                      <div className="mood-stat-count">{count}</div>
                      <div className="mood-stat-label">{percentage}%</div>
                      <div className="mood-stat-label">{mood.label}</div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* INFO CARDS */}
      <div className="info-grid">
        <div className="info-card">
          <div className="info-label">📧 Login</div>
          <div className="info-value">@{user.key}</div>
        </div>
        <div className="info-card">
          <div className="info-label">💼 Cargo</div>
          <div className="info-value">{user.role}</div>
        </div>
        <div className="info-card">
          <div className="info-label">🏢 Setor</div>
          <div className="info-value">{user.dept}</div>
        </div>
      </div>
    </div>
  );
}
