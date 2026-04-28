export const AV_COLORS = {
  'av-gold': '#C9A84C', 'av-teal': '#1D9E75', 'av-coral': '#D85A30',
  'av-blue': '#378ADD', 'av-pink': '#D4537E', 'av-purple': '#7F77DD',
  'av-green': '#639922', 'av-amber': '#BA7517'
};

export const LEVEL_LABEL = {
  dourado: '🟡 Dourado', platina: '⬜ Platina',
  diamante: '💎 Diamante', all: '🌐 Todos', rh: '🧬 RH'
};

export const LEVEL_ORDER = { dourado: 1, platina: 2, diamante: 3 };

export const LEVEL_BADGE_CLASS = {
  dourado: 'badge-dourado', platina: 'badge-platina',
  diamante: 'badge-diamante', rh: 'badge-rh'
};

export function timeAgo(iso) {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))) / 1000;
  if (diff < 60) return 'agora mesmo';
  if (diff < 3600) return `${Math.floor(diff / 60)} min atrás`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h atrás`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d atrás`;
  return new Date(iso).toLocaleDateString('pt-BR');
}

export function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function getFileIcon(name = '', mime = '') {
  const ext = name.split('.').pop().toLowerCase();
  if (['jpg','jpeg','png','gif','webp','svg'].includes(ext)) return '🖼️';
  if (['pdf'].includes(ext)) return '📄';
  if (['doc','docx'].includes(ext)) return '📝';
  if (['xls','xlsx','csv'].includes(ext)) return '📊';
  if (['ppt','pptx'].includes(ext)) return '📑';
  if (['zip','rar','7z','tar','gz'].includes(ext)) return '🗜️';
  if (['txt','md'].includes(ext)) return '📃';
  if (['mp4','avi','mov','mkv'].includes(ext)) return '🎬';
  if (['mp3','wav','ogg'].includes(ext)) return '🎵';
  if (['xml','json'].includes(ext)) return '⚙️';
  return '📁';
}

export function buildEmbedHtml(url) {
  if (!url) return null;

  // YouTube
  const ytMatch = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
  if (ytMatch) {
    return `<div class="embed-container"><iframe src="https://www.youtube.com/embed/${ytMatch[1]}" allowfullscreen loading="lazy"></iframe></div>`;
  }

  // Instagram
  if (url.includes('instagram.com/p/') || url.includes('instagram.com/reel/')) {
    const clean = url.split('?')[0].replace(/\/$/, '');
    return `<div style="padding:8px 0;max-width:400px;margin:0 auto"><iframe src="${clean}/embed" width="100%" height="320" frameborder="0" scrolling="no" allowtransparency loading="lazy" style="border-radius:12px;border:1px solid var(--border);display:block"></iframe></div>`;
  }

  // Twitter/X
  if (url.includes('twitter.com') || url.includes('x.com')) {
    return `<div style="padding:8px 0">
      <blockquote class="twitter-tweet"><a href="${url}"></a></blockquote>
      <script async src="https://platform.twitter.com/widgets.js"></script>
    </div>`;
  }

  // Spotify
  if (url.includes('spotify.com')) {
    const spotPath = url.replace('https://open.spotify.com', '');
    return `<div style="padding:8px 0"><iframe src="https://open.spotify.com/embed${spotPath}" width="100%" height="152" frameborder="0" allowfullscreen allow="autoplay; clipboard-write; encrypted-media; fullscreen" style="border-radius:12px;" loading="lazy"></iframe></div>`;
  }

  // WhatsApp — apenas link clicável
  if (url.includes('wa.me') || url.includes('whatsapp.com')) {
    return `<div style="padding:8px 0"><a href="${url}" target="_blank" rel="noopener" style="display:inline-flex;align-items:center;gap:8px;padding:10px 16px;background:#25D366;color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:13px;">💬 Abrir no WhatsApp</a></div>`;
  }

  // Generic link
  return `<div style="padding:8px 0"><a href="${url}" target="_blank" rel="noopener" style="color:var(--gold);font-size:13px;word-break:break-all;">🔗 ${url}</a></div>`;
}

export function getRoleClass(role = '') {
  const r = role.toLowerCase();
  if (r.includes('diretor') || r.includes('diretora')) return 'role-diretora';
  if (r.includes('líder') || r.includes('lider')) return 'role-lider';
  if (r.includes('financeiro') || r.includes('financeira')) return 'role-financeiro';
  if (r.includes('recepcion')) return 'role-recepcionista';
  return '';
}

export function normalizeText(t = '') {
  return t.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

export function getRoleStyle(role, is_rh, is_admin) {
  if (is_admin) return { color: 'var(--gold)', fontWeight: 700 };
  if (role === 'Diretora' || role === 'Diretor') return { color: '#ff2d7a', textShadow: '0 0 8px rgba(255,45,122,0.8)', fontWeight: 700 };
  if (role === 'Líder' || role === 'Lider') return { color: '#a855f7', textShadow: '0 0 8px rgba(168,85,247,0.8)', fontWeight: 700 };
  if (is_rh) return { color: '#f472b6', textShadow: '0 0 6px rgba(244,114,182,0.7)', fontWeight: 600 };
  return { color: 'var(--gold)', fontWeight: 500 };
}

export const CURSOR_OPTIONS = [
  { key: 'normal',  label: 'Normal (padrão)',     color: 'transparent', border: '2px solid #ccc' },
  { key: 'gold',    label: 'Bola Dourada ✨',      color: '#C9A84C' },
  { key: 'red',     label: 'Bola Vermelha 🔴',     color: '#FF2020' },
  { key: 'blue',    label: 'Bola Azul 💙',         color: '#2080FF' },
  { key: 'pink',    label: 'Bola Rosa 💗',          color: '#FF1493' },
  { key: 'white',   label: 'Bola Branca ⚪',        color: '#FFFFFF', border: '2px solid #ccc' },
  { key: 'green',   label: 'Bola Verde 💚',         color: '#22C55E' },
  { key: 'purple',  label: 'Bola Roxa 💜',          color: '#9333EA' },
  { key: 'orange',  label: 'Bola Laranja 🟠',       color: '#F97316' },
  { key: 'cyan',    label: 'Bola Ciano 🔵',         color: '#06B6D4' },
  { key: 'black',   label: 'Bola Preta ⚫',         color: '#000000' }
];

// ── TENURE (tempo de casa) ────────────────────────────────────────────────────
export function getTenureYears(hireDateStr) {
  if (!hireDateStr) return null;
  const hire = new Date(hireDateStr);
  if (isNaN(hire.getTime())) return null;
  const now = new Date();
  const years = (now - hire) / (1000 * 60 * 60 * 24 * 365.25);
  return years;
}

export function getTenureLabel(hireDateStr) {
  if (!hireDateStr) return null;
  const years = getTenureYears(hireDateStr);
  if (years === null) return null;
  if (years < 1) {
    const months = Math.floor(years * 12);
    return months <= 0 ? 'Novo colaborador' : `${months} ${months === 1 ? 'mês' : 'meses'} de casa`;
  }
  const y = Math.floor(years);
  return `${y} ${y === 1 ? 'ano' : 'anos'} de casa`;
}

export function getTenureClass(hireDateStr) {
  const years = getTenureYears(hireDateStr);
  if (years === null || years < 5) return '';
  if (years < 10) return 'tenure-prata';
  if (years < 15) return 'tenure-ouro';
  return 'tenure-cristal';
}

// ── ROLE GLOW ─────────────────────────────────────────────────────────────────
export function getRoleGlowClass(role = '', dept = '') {
  const r = (role + ' ' + dept).toLowerCase();
  if (r.includes('diretor') || r.includes('diretora') || r.includes('direção')) return 'role-glow-rosa';
  if (r.includes('líder') || r.includes('lider') || r.includes('liderança')) return 'role-glow-roxo';
  if (r.includes('financeiro') || r.includes('financeira')) return 'role-glow-laranja';
  if (r.includes('recepci')) return 'role-glow-azul';
  if (r.includes('limpeza') || r.includes('saúde') || r.includes('saude') || r.includes('enferm') || r.includes('psicol') || r.includes('nutrici')) return 'role-glow-verde';
  return '';
}

export const detectEmbed = () => {
  return false;
};
