import React, { useEffect, useMemo, useState } from 'react'

// One Spider greets you, fast. Tap/click anywhere to skip. Shown once per tab.
const SPIDERS = [
  { emoji: '🕷️', name: 'Peter Parker', color: '#c81e24' },
  { emoji: '⚡', name: 'Miles Morales', color: '#7c3aed' },
  { emoji: '🩰', name: 'Spider-Gwen', color: '#ec4899' },
  { emoji: '🕵️', name: 'Spider-Man Noir', color: '#94a3b8' },
  { emoji: '🔮', name: "Miguel O'Hara", color: '#06b6d4' },
  { emoji: '🐷', name: 'Peter Porker', color: '#fb923c' },
]

function Web({ color }) {
  return (
    <svg width="128" height="128" viewBox="0 0 150 150" className="boot-web" aria-hidden>
      <g fill="none" stroke={color} strokeOpacity="0.45" strokeWidth="1.2">
        {[...Array(8)].map((_, i) => {
          const a = (i / 8) * 2 * Math.PI
          return <line key={i} x1="75" y1="75" x2={75 + 70 * Math.cos(a)} y2={75 + 70 * Math.sin(a)} />
        })}
        {[20, 38, 56, 70].map((r, ri) => (
          <polygon key={ri} points={[...Array(8)].map((_, i) => {
            const a = (i / 8) * 2 * Math.PI
            return `${75 + r * Math.cos(a)},${75 + r * Math.sin(a)}`
          }).join(' ')} />
        ))}
      </g>
    </svg>
  )
}

export default function Boot({ label = 'Waking the web…', onDone, minMs = 750 }) {
  const [leaving, setLeaving] = useState(false)
  const s = useMemo(() => SPIDERS[Math.floor(Math.random() * SPIDERS.length)], [])
  const finish = () => { setLeaving(true); setTimeout(() => onDone && onDone(), 300) }

  useEffect(() => {
    const t = setTimeout(finish, minMs)
    return () => clearTimeout(t)
  }, []) // eslint-disable-line

  return (
    <div className={`boot ${leaving ? 'boot-out' : ''}`} style={{ '--accent': s.color }}
      onClick={finish} role="button" aria-label="Skip intro">
      <style>{BOOT_CSS}</style>
      <div className="boot-stage">
        <Web color={s.color} />
        <div className="boot-emoji">{s.emoji}</div>
      </div>
      <div className="boot-title">🕷️ Spidey <em>Studio</em></div>
      <div className="boot-label">{label}</div>
      <div className="boot-skip">tap to enter</div>
    </div>
  )
}

const BOOT_CSS = `
.boot { position:fixed; inset:0; z-index:9999; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:.35rem; cursor:pointer;
  background:radial-gradient(1000px 500px at 50% 32%,#12121c,#08080d 70%); color:#f1f1f6;
  font-family:ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  transition:opacity .3s ease, transform .3s ease; }
.boot-out { opacity:0; transform:scale(1.03); pointer-events:none; }
.boot-stage { position:relative; width:150px; height:150px; display:grid; place-items:center;
  animation:boot-pop .35s cubic-bezier(.2,.9,.3,1.3) both; }
.boot-web { position:absolute; animation:boot-spin 14s linear infinite; }
@keyframes boot-spin { to { transform:rotate(360deg); } }
@keyframes boot-pop { from{opacity:0;transform:scale(.85)} to{opacity:1;transform:none} }
.boot-emoji { font-size:3.2rem; filter:drop-shadow(0 0 16px var(--accent)); }
.boot-title { font-size:1.4rem; font-weight:800; margin-top:.9rem; }
.boot-title em { color:#ef3a40; font-style:normal; }
.boot-label { font-size:.82rem; color:#8a8a99; }
.boot-skip { font-size:.7rem; color:#55555f; margin-top:.5rem; letter-spacing:.03em; }
@media (prefers-reduced-motion:reduce){ .boot-web{ animation:none; } .boot-stage{ animation:none; } }
`
