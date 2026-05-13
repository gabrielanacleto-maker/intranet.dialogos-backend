// src/services/gamificacao.js

import { api } from './api'; // Ajuste o import conforme seu arquivo de API

export const gamificacaoService = {
  // Obter pontos de um usuário
  getUserPoints: async (userKey) => {
    try {
      const response = await api.get(`/api/gamificacao/user-points/${userKey}`);
      return response.data;
    } catch (error) {
      console.error('Erro ao obter pontos:', error);
      throw error;
    }
  },

  // Obter badges de um usuário
  getUserBadges: async (userKey) => {
    try {
      const response = await api.get(`/api/gamificacao/user-badges/${userKey}`);
      return response.data;
    } catch (error) {
      console.error('Erro ao obter badges:', error);
      throw error;
    }
  },

  // Obter leaderboard (mensal ou geral)
  getLeaderboard: async (month = null) => {
    try {
      const url = month 
        ? `/api/gamificacao/leaderboard?month=${month}`
        : '/api/gamificacao/leaderboard';
      const response = await api.get(url);
      return response.data;
    } catch (error) {
      console.error('Erro ao obter leaderboard:', error);
      throw error;
    }
  },

  // Obter dashboard completo
  getGamificationDashboard: async (userKey) => {
    try {
      const response = await api.get(`/api/gamificacao/dashboard/${userKey}`);
      return response.data;
    } catch (error) {
      console.error('Erro ao obter dashboard:', error);
      throw error;
    }
  },

  // Obter conquistas
  getUserAchievements: async (userKey) => {
    try {
      const response = await api.get(`/api/gamificacao/user-achievements/${userKey}`);
      return response.data;
    } catch (error) {
      console.error('Erro ao obter conquistas:', error);
      throw error;
    }
  },

  // Admin: Adicionar pontos
  addPoints: async (userKey, points, reason, actionType) => {
    try {
      const response = await api.post('/api/gamificacao/add-points', {
        user_key: userKey,
        points: points,
        reason: reason,
        action_type: actionType
      });
      return response.data;
    } catch (error) {
      console.error('Erro ao adicionar pontos:', error);
      throw error;
    }
  },

  // Admin: Conceder badge
  awardBadge: async (userKey, badgeType, badgeName, description, icon) => {
    try {
      const response = await api.post('/api/gamificacao/award-badge', {
        user_key: userKey,
        badge_type: badgeType,
        badge_name: badgeName,
        description: description,
        icon: icon
      });
      return response.data;
    } catch (error) {
      console.error('Erro ao conceder badge:', error);
      throw error;
    }
  }
};
