import { useMemo } from 'react';

const themes = [
  {
    id: 'dia_dos_namorados',
    name: 'Dia dos Namorados',
    start: { month: 5, day: 1 },
    end: { month: 7, day: 15 },
    colors: {
      primary: '#8B0000',
      secondary: '#4A0404',
      gold: '#D4A843',
      accent: '#FFE4E1',
      bg1: '#1a0404',
      bg2: '#0d0202',
      surface: 'rgba(26,4,4,0.8)',
      border: 'rgba(212,168,67,0.12)',
    },
    bgClass: 'tema-dia-dos-namorados',
    icon: '💕',
    decoration: '❤️💕🌹🥀💌💋',
    banner: 'Onde o amor e o cuidado andam juntos ❤️',
  },
];

function isWithinPeriod(date, start, end) {
  const d = date.getMonth() + 1;
  const day = date.getDate();

  if (start.month === end.month && start.day <= end.day) {
    if (d === start.month && day >= start.day && day <= end.day) return true;
  }

  if (end.month < start.month) {
    if (d > start.month || d < end.month) return true;
    if (d === start.month && day >= start.day) return true;
    if (d === end.month && day <= end.day) return true;
  }

  if (d === start.month && day >= start.day && d < end.month) return true;
  if (d === end.month && day <= end.day && d > start.month) return true;
  if (d > start.month && d < end.month) return true;

  return false;
}

export function getActiveTheme() {
  const now = new Date();
  for (const theme of themes) {
    if (isWithinPeriod(now, theme.start, theme.end)) {
      return theme;
    }
  }
  return null;
}

export function getThemeStyle() {
  const theme = getActiveTheme();
  if (!theme) return {};
  return {
    '--tema-primary': theme.colors.primary,
    '--tema-secondary': theme.colors.secondary,
    '--tema-gold': theme.colors.gold,
    '--tema-accent': theme.colors.accent,
    '--tema-bg1': theme.colors.bg1,
    '--tema-bg2': theme.colors.bg2,
    '--tema-surface': theme.colors.surface,
    '--tema-border': theme.colors.border,
  };
}

export function useTheme() {
  return useMemo(() => getActiveTheme(), []);
}

export function ThemeDecorations({ density = 20 }) {
  const theme = getActiveTheme();
  if (!theme) return null;

  const chars = theme.decoration.split('');
  const items = [];

  for (let i = 0; i < density; i++) {
    items.push(
      <span
        key={i}
        style={{
          position: 'absolute',
          top: `${((i * 7.3 + 3) % 100)}%`,
          left: `${((i * 13.7 + 7) % 100)}%`,
          fontSize: `${10 + (i % 5) * 4}px`,
          opacity: 0.06 + (i % 3) * 0.04,
          pointerEvents: 'none',
          transform: `rotate(${i * 37}deg)`,
          animation: `floatY ${4 + (i % 4) * 2}s ease-in-out infinite`,
          animationDelay: `${i * 0.4}s`,
          zIndex: 0,
        }}
      >
        {chars[i % chars.length]}
      </span>
    );
  }

  return <>{items}</>;
}

export function FloatingHearts({ count = 12 }) {
  const theme = getActiveTheme();
  if (!theme || theme.id !== 'dia_dos_namorados') return null;

  const hearts = [];

  for (let i = 0; i < count; i++) {
    const size = 10 + (i % 5) * 8;
    const left = ((i * 9.7 + 2) % 100);
    const delay = i * 1.2;
    const duration = 8 + (i % 4) * 4;
    hearts.push(
      <span
        key={i}
        style={{
          position: 'fixed',
          left: `${left}%`,
          bottom: '-20px',
          fontSize: `${size}px`,
          opacity: 0.15 + (i % 3) * 0.1,
          pointerEvents: 'none',
          zIndex: 9998,
          animation: `heartFloat ${duration}s ease-in-out infinite`,
          animationDelay: `${delay}s`,
        }}
      >
        {i % 3 === 0 ? '❤️' : i % 3 === 1 ? '💕' : '🌹'}
      </span>
    );
  }

  return <>{hearts}</>;
}

export function ThemeAnimations() {
  const theme = getActiveTheme();
  if (!theme) return null;

  return (
    <style>
      {`
        @keyframes floatY {
          0%, 100% {
            transform: translateY(0px);
          }
          50% {
            transform: translateY(-12px);
          }
        }

        @keyframes heartFloat {
          0% {
            transform: translateY(0px) scale(1);
            opacity: 0;
          }
          20% {
            opacity: 0.25;
          }
          80% {
            opacity: 0.18;
          }
          100% {
            transform: translateY(-100vh) scale(1.25);
            opacity: 0;
          }
        }

        @keyframes pulseRomance {
          0%, 100% {
            transform: scale(1);
            opacity: 0.8;
          }
          50% {
            transform: scale(1.06);
            opacity: 1;
          }
        }

        @keyframes floatLove {
          0%, 100% {
            transform: translateY(0px) rotate(0deg);
          }
          50% {
            transform: translateY(-4px) rotate(4deg);
          }
        }
      `}
    </style>
  );
}

export function ThemeBanner() {
  const theme = getActiveTheme();
  if (!theme) return null;

  return (
    <div
      style={{
        textAlign: 'center',
        padding: '6px 16px',
        background: `linear-gradient(90deg, transparent, ${theme.colors.primary}22, transparent)`,
        borderBottom: `1px solid ${theme.colors.border}`,
      }}
    >
      <span style={{
        fontSize: 12,
        fontWeight: 600,
        letterSpacing: 0.5,
        background: `linear-gradient(135deg, ${theme.colors.gold}, ${theme.colors.primary})`,
        WebkitBackgroundClip: 'text',
        WebkitTextFillColor: 'transparent',
        backgroundClip: 'text',
      }}>
        {theme.banner || `${theme.icon} ${theme.name} — Clínica Diálogos ${theme.icon}`}
      </span>
    </div>
  );
}

export function RomanticAvatarDecoration({ children }) {
  const theme = getActiveTheme();

  if (!theme || theme.id !== 'dia_dos_namorados') {
    return children;
  }

  return (
    <div
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {/* Aura vinho */}
      <div
        style={{
          position: 'absolute',
          inset: -8,
          borderRadius: '50%',
          background: `
            radial-gradient(circle,
              rgba(139,0,32,0.35) 0%,
              rgba(90,0,20,0.18) 45%,
              transparent 75%)
          `,
          filter: 'blur(10px)',
          zIndex: 0,
          animation: 'pulseRomance 3s ease-in-out infinite',
        }}
      />

      {/* Borda temática */}
      <div
        style={{
          position: 'absolute',
          inset: -4,
          borderRadius: '50%',
          border: '3px solid #8B0A28',
          boxShadow: `
            0 0 10px rgba(139,10,40,0.7),
            0 0 18px rgba(180,20,60,0.5),
            inset 0 0 8px rgba(255,215,230,0.12)
          `,
          zIndex: 1,
        }}
      />

      {/* Conteúdo original */}
      <div style={{ position: 'relative', zIndex: 2 }}>
        {children}
      </div>

      {/* Coração decorativo */}
      <span
        style={{
          position: 'absolute',
          top: '-8px',
          left: '-6px',
          fontSize: 20,
          zIndex: 3,
          filter: 'drop-shadow(0 0 6px rgba(255,50,90,0.8))',
          animation: 'floatLove 2.8s ease-in-out infinite',
          userSelect: 'none',
          pointerEvents: 'none',
        }}
      >
        ❤️
      </span>

      {/* Taça decorativa */}
      <span
        style={{
          position: 'absolute',
          right: '-8px',
          bottom: '8px',
          fontSize: 18,
          zIndex: 3,
          filter: 'drop-shadow(0 0 6px rgba(120,0,30,0.8))',
          animation: 'floatLove 3.4s ease-in-out infinite',
          animationDelay: '0.8s',
          userSelect: 'none',
          pointerEvents: 'none',
        }}
      >
        🍷
      </span>
    </div>
  );
}

export default themes;
