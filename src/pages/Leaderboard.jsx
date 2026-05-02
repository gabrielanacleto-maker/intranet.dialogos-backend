// src/pages/Leaderboard.jsx

import React, { useState, useEffect } from 'react';
import { gamificacaoService } from '../services/gamificacao';
import '../styles/Leaderboard.css';

export default function Leaderboard() {
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);
  const [month, setMonth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchLeaderboard();
  }, [month]);

  const fetchLeaderboard = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await gamificacaoService.getLeaderboard(month);
      setLeaderboard(data.leaderboard || []);
    } catch (err) {
      setError('Erro ao carregar leaderboard');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const getMedalEmoji = (position) => {
    if (position === 1) return '🥇';
    if (position === 2) return '🥈';
    if (position === 3) return '🥉';
    return `${position}º`;
  };

  if (loading) {
    return (
      <div className="leaderboard-container">
        <div className="loading">
          <div className="spinner"></div>
          <p>Carregando ranking...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="leaderboard-container">
      <div className="leaderboard-header">
        <h1>🏆 Leaderboard</h1>
        <p className="subtitle">Ranking mensal da equipe</p>
      </div>

      <div className="leaderboard-content">
        {error ? (
          <div className="error-message">{error}</div>
        ) : leaderboard.length === 0 ? (
          <div className="empty-state">
            <p>Nenhum usuário no ranking ainda</p>
          </div>
        ) : (
          <div className="leaderboard-list">
            {leaderboard.map((user, index) => (
              <div key={user.user_key} className={`leaderboard-item position-${user.position}`}>
                <div className="medal">
                  <span className="medal-emoji">{getMedalEmoji(user.position)}</span>
                </div>

                <div className="user-info">
                  <div className="user-avatar" style={{ backgroundColor: user.color }}>
                    {user.initials}
                  </div>
                  <div className="user-details">
                    <h3>{user.name}</h3>
                    <span className="position-text">Posição #{user.position}</span>
                  </div>
                </div>

                <div className="points-section">
                  <div className="points-display">
                    <span className="points-number">{user.points}</span>
                    <span className="points-label">pontos</span>
                  </div>
                </div>

                <div className="progress-bar">
                  <div 
                    className="progress-fill"
                    style={{ 
                      width: `${Math.min((user.points / 1000) * 100, 100)}%`,
                      backgroundColor: user.color
                    }}
                  ></div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="leaderboard-stats">
        <div className="stat">
          <span className="stat-label">Total de Participantes</span>
          <span className="stat-value">{leaderboard.length}</span>
        </div>
        {leaderboard.length > 0 && (
          <>
            <div className="stat">
              <span className="stat-label">Maior Pontuação</span>
              <span className="stat-value">{leaderboard[0]?.points || 0}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Pontos Médios</span>
              <span className="stat-value">
                {Math.round(leaderboard.reduce((sum, u) => sum + u.points, 0) / leaderboard.length)}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
