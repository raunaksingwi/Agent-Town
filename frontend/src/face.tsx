// An agent's face in the Office: a drawn portrait in the agent's colour. Its hair, skin and glasses
// come from its slug, so the same agent always has the same face, and agents side by side look different.

import { seedOf } from './city/layout'

// each hairstyle is [behind the head, over the forehead], on a 64 by 64 face
const HAIR: [string, string][] = [
  ['', 'M21 25C21 14 28 11 33 11C40 11 44 15 43 25C41 19 36 17 31 18C26 18 23 21 21 25Z'],
  ['', 'M20 26C19 15 26 10 33 10C41 10 45 16 44 26L42 22C38 20 30 21 24 17C22 20 21 23 20 26Z'],
  ['M19 26C18 13 26 9 32 9C39 9 46 13 45 26L47 46C40 48 24 48 17 46Z', 'M20 27C20 16 26 12 32 12C38 12 44 16 44 27C40 21 35 18 30 17C27 20 24 23 20 27Z'],
  ['', 'M26 10A6 6 0 1 0 38 10A6 6 0 1 0 26 10ZM21 25C21 15 27 12 32 12C38 12 43 15 43 25C40 19 36 18 32 18C27 18 23 20 21 25Z'],
  ['M16 27C13 12 23 6 32 7C41 6 51 12 48 27C50 31 46 35 43 32L21 32C18 35 14 31 16 27Z', ''],
  ['', 'M21 24C22 15 27 13 32 13C37 13 42 15 43 24C40 19 36 17.5 32 17.5C28 17.5 24 19 21 24Z'],
]
const SKIN = ['#f1cdaa', '#e8b48c', '#d9a07a', '#c68b63', '#a86f4a', '#8d5a3b']
const HAIR_COLOR = ['#1a1a1a', '#2b1d14', '#6b4a2b', '#b5562b', '#c9a15e', '#8a8a8a']

/** `c` mixed toward white by `t` (0..1): the portrait's background */
function tint(c: string, t: number) {
  const n = parseInt(c.replace('#', '').padEnd(6, '0').slice(0, 6), 16)
  const ch = (s: number) => Math.round(((n >> s) & 255) + (255 - ((n >> s) & 255)) * t)
  return `rgb(${ch(16)}, ${ch(8)}, ${ch(0)})`
}

export function Face({ slug, color, asleep = false }: { slug: string; color: string; asleep?: boolean }) {
  const s = seedOf(slug)
  const [back, front] = HAIR[s % HAIR.length]
  const skin = SKIN[(s >> 4) % SKIN.length], hair = HAIR_COLOR[(s >> 8) % HAIR_COLOR.length]
  const glasses = (s >> 12) % 4 === 0
  return (
    <svg viewBox="0 0 64 64" width="100%" height="100%" aria-hidden="true">
      <rect width="64" height="64" fill={tint(color, 0.82)} />
      {back && <path d={back} fill={hair} />}
      <path d="M8 66C8 49 18 43 32 43C46 43 56 49 56 66Z" fill={color} />
      <rect x="27" y="34" width="10" height="11" rx="4" fill={skin} />
      <ellipse cx="32" cy="27" rx="11" ry="12.5" fill={skin} />
      {front && <path d={front} fill={hair} />}
      {asleep
        ? <g fill="none" stroke="#2b211c" strokeWidth="1.4" strokeLinecap="round"><path d="M26.5 28.5Q28 29.8 29.5 28.5" /><path d="M34.5 28.5Q36 29.8 37.5 28.5" /></g>
        : <g fill="#2b211c"><circle cx="28" cy="28" r="1.5" /><circle cx="36" cy="28" r="1.5" /></g>}
      <path d="M29 33.5Q32 36 35 33.5" stroke="#3a2a1e" strokeWidth="1.4" fill="none" strokeLinecap="round" />
      {glasses && <g fill="none" stroke="#1f1f1f" strokeWidth="1.3"><circle cx="28" cy="28" r="3.6" /><circle cx="36" cy="28" r="3.6" /><path d="M31.6 28h.8" /></g>}
    </svg>
  )
}
