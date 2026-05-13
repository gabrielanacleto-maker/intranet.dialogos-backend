export default function Loading({ message = 'Entrando...' }) {
  return (
    <div
      style={{
        height: '100vh', width: '100%',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background:
          'radial-gradient(ellipse 100% 70% at 50% 0%, rgba(212,168,67,0.08) 0%, transparent 60%),' +
          'radial-gradient(ellipse 80% 60% at 20% 80%, rgba(212,168,67,0.04) 0%, transparent 50%),' +
          'radial-gradient(ellipse 60% 50% at 80% 30%, rgba(100,80,30,0.06) 0%, transparent 40%),' +
          'linear-gradient(160deg, #050504 0%, #0a0a08 40%, #0f0e0a 100%)',
        color: '#e8e0cc', flexDirection: 'column', gap: 24,
        position: 'fixed', inset: 0, zIndex: 9999,
      }}
    >
      <img
        src="/logo-clinica-fivecon.ico"
        alt="Clínica Diálogos"
        style={{ width: 48, height: 48, objectFit: 'contain', filter: 'brightness(0) saturate(100%) sepia(60%) hue-rotate(10deg) brightness(0.9)' }}
      />
      <div style={{
        width: 40, height: 40,
        border: '3px solid rgba(212,168,67,0.15)',
        borderTop: '3px solid var(--gold, #D4A843)',
        borderRadius: '50%',
        animation: 'loadingSpin 0.8s linear infinite',
        boxShadow: '0 0 30px rgba(212,168,67,0.1)',
      }} />

      <div style={{ textAlign: 'center' }}>
        <p style={{ margin: 0, fontSize: 14, fontWeight: 600, letterSpacing: 1, color: 'var(--gold, #D4A843)' }}>
          {message}
        </p>
        <p style={{ margin: '6px 0 0', fontSize: 12, color: 'rgba(232,224,204,0.4)', letterSpacing: 0.5 }}>
          Clínica Diálogos
        </p>
      </div>

      <style>{`
        @keyframes loadingSpin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
