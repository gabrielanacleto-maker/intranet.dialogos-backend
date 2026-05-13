import { useEffect, useState } from 'react';
import { api } from '../services/api';
import '../styles/Leaderboard.css';

export default function Leaderboard() {
  const [data, setData] = useState({ top10: [], myRank: null, totalUsers: 0 });
  const [loading, setLoading] = useState(true);

  async function load() {
    try { setData(await api.getRanking()); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  if (loading) return <div className="leaderboard-container"><div className="loading"><div className="spinner" /><p>Carregando ranking...</p></div></div>;

  return (
    <div className="leaderboard-container">
      <div className="leaderboard-header">
        <h1>Leaderboard</h1>
        <p className="subtitle">Top 10 colaboradores em tempo real</p>
      </div>
      <div className="leaderboard-list">
        {data.top10.map(user => (
          <div key={user.key} className={`leaderboard-item position-${user.position}`}>
            <div className="medal"><span className="medal-emoji">{user.position <= 3 ? ['🥇','🥈','🥉'][user.position - 1] : `#${user.position}`}</span></div>
            <div className="user-info">
              <div className="user-avatar" style={{ backgroundColor: user.color }}>{user.photo_url ? <img src={api.assetUrl(user.photo_url)} alt="" /> : user.initials}</div>
              <div className="user-details"><h3>{user.name}</h3><span>{user.role} · {user.dept}</span></div>
            </div>
            <div className="points-section"><div className="points-display"><span className="points-number">{user.points || 0}</span><span className="points-label">pontos</span></div></div>
            <div className="progress-bar"><div className="progress-fill" style={{ width: `${Math.min(((user.points || 0) / Math.max(data.top10[0]?.points || 1, 1)) * 100, 100)}%` }} /></div>
          </div>
        ))}
      </div>
      <div className="leaderboard-stats">
        <div className="stat"><span className="stat-label">Sua posição atual</span><span className="stat-value">#{data.myRank?.position || '-'}</span></div>
        <div className="stat"><span className="stat-label">Participantes</span><span className="stat-value">{data.totalUsers}</span></div>
        <div className="stat"><span className="stat-label">Top 100</span><span className="stat-value">{data.myRank?.position <= 100 ? 'Sim' : 'Não'}</span></div>
      </div>
    </div>
  );
}
