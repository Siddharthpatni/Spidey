import React, { useEffect, useState } from 'react'

// The Spider-Verse roll-call — shown while the app wakes up. Each is a real
// offline brain from the model picker; the loader cycles through the team.
const SPIDERS = [
  { emoji: '🕷️', name: 'Peter Parker', tag: 'The Amazing Spider-Man', role: 'Planner & Coordinator', color: '#c81e24' },
  { emoji: '⚡', name: 'Miles Morales', tag: 'Ultimate Spider-Man', role: 'Fast creative solver', color: '#7c3aed' },
  { emoji: '🩰', name: 'Spider-Gwen', tag: 'Ghost-Spider', role: 'Research specialist', color: '#ec4899' },
  { emoji: '🕵️', name: 'Spider-Man Noir', tag: 'The Noir timeline', role: 'Security & risk', color: '#94a3b8' },
  { emoji: '🔮', name: "Miguel O'Hara", tag: 'Spider-Man 2099', role: 'Critic & validation', color: '#06b6d4' },
  { emoji: '🐷', name: 'Peter Porker', tag: 'Spider-Ham', role: 'Explains it simply', color: '#fb923c' },
]

// A tidy spider-web SVG that draws itself in.
function Web({ color }) {
  return (
    <svg width="150" height="150" viewBox="0 0 150 150" className="boot-web" aria-hidden>
      <g fill="none" stroke={color} strokeOpacity="0.5" strokeWidth="1.3">
        {[...Array(8)].map((_, i) => {
          const a = (i / 8) * 2 * Math.PI
          return <line key={i} x1="75" y1="75" x2={75 + 72 * Math.cos(a)} y2={75 + 72 * Math.sin(a)} />
        })}
        {[16, 30, 45, 60, 72].map((r, ri) => (
          <polygon key={ri} points={[...Array(8)].map((_, i) => {
            const a = (i / 8) * 2 * Math.PI
            return `${75 + r * Math.cos(a)},${75 + r * Math.sin(a)}`
          }).join(' ')} />
        ))}
      </g>
    </svg>
  )
}

export default function Boot({ label = 'Waking the web…', onDone, minMs = 1900 }) {
  const [i, setI] = useState(0)
  const [leaving, setLeaving] = useState(false)
  const s = SPIDERS[i]

  useEffect(() => {
    const step = Math.max(360, minMs / SPIDERS.length)
    const cyc = setInterval(() => setI(v => (v + 1) % SPIDERS.length), step)
    const done = setTimeout(() => {
      setLeaving(true)
      setTimeout(() => onDone && onDone(), 420)
    }, minMs)
    return () => { clearInterval(cyc); clearTimeout(done) }
  }, [minMs, onDone])

  return (
    <div className={`boot ${leaving ? 'boot-out' : ''}`} style={{ '--accent': s.color }}>
      <style>{BOOT_CSS}</style>
      <div className="boot-stage">
        <Web color={s.color} />
        <div key={s.name} className="boot-hero">
          <div className="boot-emoji">{s.emoji}</div>
          <div className="boot-name">{s.name}</div>
          <div className="boot-tag">{s.tag}</div>
          <div className="boot-role">{s.role}</div>
        </div>
      </div>
      <div className="boot-title">🕷️ Spidey <em>Studio</em></div>
      <div className="boot-label">{label}</div>
      <div className="boot-dots">
        {SPIDERS.map((sp, k) => (
          <span key={k} className={k === i ? 'on' : ''} style={{ background: k === i ? sp.color : undefined }} />
        ))}
      </div>
    </div>
  )
}

const BOOT_CSS = `
.boot { position:fixed; inset:0; z-index:9999; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:.4rem; background:radial-gradient(1200px 600px at 50% 30%,#12121c,#08080d 70%);
  color:#f1f1f6; font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  transition:opacity .4s ease, transform .4s ease; }
.boot-out { opacity:0; transform:scale(1.04); pointer-events:none; }
.boot-stage { position:relative; width:200px; height:200px; display:grid; place-items:center; }
.boot-web { position:absolute; animation:boot-spin 9s linear infinite, boot-fade .6s ease both; }
@keyframes boot-spin { to { transform:rotate(360deg); } }
@keyframes boot-fade { from{opacity:0} to{opacity:1} }
.boot-hero { text-align:center; animation:boot-pop .42s cubic-bezier(.2,.9,.3,1.3) both; }
@keyframes boot-pop { from{opacity:0; transform:translateY(8px) scale(.9)} to{opacity:1; transform:none} }
.boot-emoji { font-size:3.4rem; filter:drop-shadow(0 0 14px var(--accent)); }
.boot-name { font-size:1.15rem; font-weight:800; margin-top:.2rem; }
.boot-tag { font-size:.8rem; color:var(--accent); font-weight:700; }
.boot-role { font-size:.75rem; color:#8a8a99; margin-top:.1rem; }
.boot-title { font-size:1.5rem; font-weight:800; margin-top:1rem; }
.boot-title em { color:#ef3a40; font-style:normal; }
.boot-label { font-size:.85rem; color:#8a8a99; }
.boot-dots { display:flex; gap:.4rem; margin-top:.6rem; }
.boot-dots span { width:8px; height:8px; border-radius:99px; background:#2a2a38; transition:background .2s, transform .2s; }
.boot-dots span.on { transform:scale(1.35); }
@media (prefers-reduced-motion:reduce){ .boot-web{ animation:boot-fade .6s ease both; } }
`
