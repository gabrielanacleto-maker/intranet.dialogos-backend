export default function Loading() {
  return (
    <div
      style={{
        height: '100vh',
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#000000',
        color: '#fff',
        flexDirection: 'column',
        gap: '16px'
      }}
    >
        <img
        src="/logo.png"
        alt="Logo"
        style={{ width: '120px', marginBottom: '8px' }}
      />

      <div
        style={{
          width: '60px',
          height: '60px',
          border: '5px solid rgba(255,255,255,0.2)',
          borderTop: '5px solid #fff',
          borderRadius: '50%',
          animation: 'spin 1s linear infinite'
        }}
      />

      <h2>Loading...</h2>

      <style>
        {`
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}
      </style>
    </div>
  )
}