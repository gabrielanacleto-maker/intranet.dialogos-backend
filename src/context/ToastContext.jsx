import { createContext, useContext, useState, useCallback } from 'react';

const ToastContext = createContext(null);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const toast = useCallback((message, type = 'info') => {
    const id = Date.now();
    setToasts(t => [...t, { id, message, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3500);
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div style={{ position: 'fixed', bottom: 20, right: 20, zIndex: 9999, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {toasts.map(t => (
          <div key={t.id} style={{
            background: t.type === 'error' ? '#b91c1c' : t.type === 'success' ? '#166534' : '#1f2937',
            color: '#fff', padding: '10px 16px', borderRadius: 10, fontSize: 13,
            boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
            animation: 'slideIn 0.2s ease',
          }}>
            {t.message}
          </div>
        ))}
      </div>
      <style>{`@keyframes slideIn{from{transform:translateX(40px);opacity:0}to{transform:translateX(0);opacity:1}}`}</style>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
