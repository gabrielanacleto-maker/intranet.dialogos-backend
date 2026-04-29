const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function getToken() {
  return localStorage.getItem('dialogos_token');
}

async function req(method, path, body, isForm = false) {
  const headers = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (!isForm) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: isForm ? body : (body ? JSON.stringify(body) : undefined),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Erro desconhecido' }));
    throw new Error(err.detail || 'Erro na requisição');
  }
  return res.json();
}

export const api = {
  // Auth
  login: (key, password) => req('POST', '/api/auth/login', { key, password }),
  changePassword: (current_password, new_password) =>
    req('POST', '/api/auth/change-password', { current_password, new_password }),

  // Users
  getUsers: () => req('GET', '/api/users'),
  createUser: (data) => req('POST', '/api/users', data),
  updateUser: (key, data) => req('PUT', `/api/users/${key}`, data),
  deleteUser: (key) => req('DELETE', `/api/users/${key}`),
  resetPassword: (key, new_password) => req('POST', `/api/users/${key}/reset-password`, { new_password }),
  uploadPhoto: (file) => {
    const fd = new FormData(); fd.append('file', file);
    return req('POST', '/api/users/me/photo', fd, true);
  },
  updatePoints: (key, points) => req('PUT', `/api/users/${key}/points`, { points }),

  // Security Logs
  getLogs: () => req('GET', '/api/security-logs'),

  // Posts
  getPosts: (feed = 'feed') => req('GET', `/api/posts?feed=${feed}`),
  createPost: (data) => req('POST', '/api/posts', data),
  deletePost: (id) => req('DELETE', `/api/posts/${id}`),
  pinPost: (id) => req('POST', `/api/posts/${id}/pin`),
  likePost: (id) => req('POST', `/api/posts/${id}/like`),
  commentPost: (id, text) => req('POST', `/api/posts/${id}/comment`, { text }),
  uploadPostImage: (file) => {
    const fd = new FormData(); fd.append('file', file);
    return req('POST', '/api/posts/upload-image', fd, true);
  },

  // Mural
  getMural: () => req('GET', '/api/mural'),
  createMural: (data) => req('POST', '/api/mural', data),
  deleteMural: (id) => req('DELETE', `/api/mural/${id}`),
  uploadMuralImage: (file) => {
    const fd = new FormData(); fd.append('file', file);
    return req('POST', '/api/mural/upload-image', fd, true);
  },

  // Folders
  getFolders: () => req('GET', '/api/folders'),
  createFolder: (data) => req('POST', '/api/folders', data),
  updateFolder: (id, data) => req('PUT', `/api/folders/${id}`, data),
  deleteFolder: (id) => req('DELETE', `/api/folders/${id}`),
  getFolderFiles: (id) => req('GET', `/api/folders/${id}/files`),
  uploadFolderFile: (folderId, file) => {
    const fd = new FormData(); fd.append('file', file);
    return req('POST', `/api/folders/${folderId}/files`, fd, true);
  },
  deleteFolderFile: (folderId, fileId) => req('DELETE', `/api/folders/${folderId}/files/${fileId}`),

  // Ouvidoria
  getOuvidoria: () => req('GET', '/api/ouvidoria'),
  createOuvidoria: (data) => req('POST', '/api/ouvidoria', data),
  updateOuvidoriaStatus: (id, status) => req('PUT', `/api/ouvidoria/${id}/status`, { status }),
  respondOuvidoria: (id, text) => req('POST', `/api/ouvidoria/${id}/respond`, { text }),

  // Chat
  getChat: (roomId) => req('GET', `/api/chat/${roomId}`),
  sendChat: (room_id, text) => req('POST', '/api/chat', { room_id, text }),

  // Social / Comunidade
  getSocialRooms: () => req('GET', '/api/social-rooms'),
  createSocialRoom: (data) => req('POST', '/api/social-rooms', data),
  deleteSocialRoom: (roomId) => req('DELETE', `/api/social-rooms/${roomId}`),
  getSocialRoomMembers: (roomId) => req('GET', `/api/social-rooms/${roomId}/members`),
  addSocialRoomMember: (roomId, userKey) => req('POST', `/api/social-rooms/${roomId}/members/${userKey}`),
  removeSocialRoomMember: (roomId, userKey) => req('DELETE', `/api/social-rooms/${roomId}/members/${userKey}`),
  getSocialRoomFiles: (roomId) => req('GET', `/api/social-rooms/${roomId}/files`),
  uploadSocialRoomFile: (roomId, file) => {
    const fd = new FormData(); fd.append('file', file);
    return req('POST', `/api/social-rooms/${roomId}/files`, fd, true);
  },
  deleteSocialRoomFile: (roomId, fileId) => req('DELETE', `/api/social-rooms/${roomId}/files/${fileId}`),

  // Organogram
  getOrganogram: () => req('GET', '/api/organogram'),
  saveOrganogram: (entries) => req('POST', '/api/organogram', entries),

  // Ranking
  getRanking: () => req('GET', '/api/ranking'),

  // Mood
  saveMood: (data) => req('POST', '/api/mood', data),
  getMoodHistory: () => req('GET', '/api/mood/history'),


  // Calendário
  getCalendarEvents: () => req('GET', '/api/calendar'),
  createCalendarEvent: (data) => req('POST', '/api/calendar', data),
  updateCalendarEvent: (id, data) => req('PUT', `/api/calendar/${id}`, data),
  deleteCalendarEvent: (id) => req('DELETE', `/api/calendar/${id}`),

  // Tabela de Preços
  getPriceDoctors: (folderId) => req('GET', `/api/price-doctors?folder_id=${folderId}`),
  createPriceDoctor: (data) => req('POST', '/api/price-doctors', data),
  updatePriceDoctor: (id, data) => req('PUT', `/api/price-doctors/${id}`, data),
  deletePriceDoctor: (id) => req('DELETE', `/api/price-doctors/${id}`),
  getPriceProcedures: (doctorId) => req('GET', `/api/price-procedures/${doctorId}`),
  createPriceProcedure: (data) => req('POST', '/api/price-procedures', data),
  updatePriceProcedure: (id, data) => req('PUT', `/api/price-procedures/${id}`, data),
  deletePriceProcedure: (id) => req('DELETE', `/api/price-procedures/${id}`),
  downloadPriceTable: async (folderId) => {
    const headers = {};
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${BASE}/api/price-export/${folderId}`, { headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Erro ao baixar tabela de preços' }));
      throw new Error(err.detail || 'Erro ao baixar tabela de preços');
    }
    return res.blob();
  },

  assetUrl: (url) => url ? (url.startsWith('http') ? url : `${BASE}${url}`) : null,
};
