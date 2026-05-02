import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { api } from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [allUsers, setAllUsers] = useState({});

  const login = useCallback(async (key, password) => {
    const data = await api.login(key, password);
    localStorage.setItem('dialogos_token', data.token);
    setUser(data.user);
    setMustChangePassword(data.must_change_password);
    // Carregar todos os usuários
    try {
      const users = await api.getUsers();
      const map = {};
      users.forEach(u => { map[u.key] = u; });
      setAllUsers(map);
    } catch (_) {}
    return data;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('dialogos_token');
    setUser(null);
    setMustChangePassword(false);
    setAllUsers({});
  }, []);

  const refreshUsers = useCallback(async () => {
    try {
      const users = await api.getUsers();
      const map = {};
      users.forEach(u => { map[u.key] = u; });
      setAllUsers(map);
    } catch (_) {}
  }, []);

  // Logout por inatividade (1 hora sem atividade)
  useEffect(() => {
    if (!user) return;

    let inactivityTimer;

    const resetTimer = () => {
      clearTimeout(inactivityTimer);
      
      inactivityTimer = setTimeout(() => {
        console.log('⏰ Logout por inatividade após 1 hora');
        logout();
        alert('Sua sessão expirou por inatividade. Faça login novamente.');
      }, 3600000); // 1 hora em milissegundos
    };

    window.addEventListener('mousedown', resetTimer);
    window.addEventListener('keydown', resetTimer);
    window.addEventListener('scroll', resetTimer);
    window.addEventListener('touchstart', resetTimer);

    resetTimer();

    return () => {
      clearTimeout(inactivityTimer);
      window.removeEventListener('mousedown', resetTimer);
      window.removeEventListener('keydown', resetTimer);
      window.removeEventListener('scroll', resetTimer);
      window.removeEventListener('touchstart', resetTimer);
    };
  }, [user, logout]);

  const canPostNovidades = user && (
    user.is_admin || user.is_admin_user || user.is_rh ||
    user.level === 'platina' || user.level === 'diamante'
  );

  const canSeeNovidades = canPostNovidades;
  const canAdmin = user && (user.is_admin || user.is_admin_user);
  const isLevel3 = user?.access_level >= 3;
  const isLevel2 = user?.access_level >= 2;

  return (
    <AuthContext.Provider value={{
      user, allUsers, mustChangePassword, setMustChangePassword,
      login, logout, refreshUsers,
      canPostNovidades, canSeeNovidades, canAdmin, isLevel2, isLevel3
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
