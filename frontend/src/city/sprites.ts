// Everything on the map, drawn in code: buildings, trees, and the agents' NPCs. Units are "art pixels"
// (16 per tile). A Paint draws the same shapes two ways: crisp pixels with outlines (retro), or smooth
// rounded shapes with soft light (fantasy, office).

import type { BrainLook } from './brain'
import type { RGB } from './layout'
import { houseSize, type BuildingStyle, type HouseSpec } from './kinds'
import type { Theme } from './themes'

export const hash = (x: number, y: number) => {
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263)) | 0
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}
export const css = (c: RGB, k = 1, a = 1) =>
  `rgba(${Math.max(0, Math.min(255, c[0] * k)) | 0},${Math.max(0, Math.min(255, c[1] * k)) | 0},${Math.max(0, Math.min(255, c[2] * k)) | 0},${a})`
const mix = (a: RGB, b: RGB, t: number): RGB => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]

export class Paint {
  readonly c: CanvasRenderingContext2D
  readonly t: Theme
  readonly seed: number
  constructor(c: CanvasRenderingContext2D, t: Theme, seed = 1) { this.c = c; this.t = t; this.seed = seed }

  rect(x: number, y: number, w: number, h: number, col: RGB, k = 1) {
    const c = this.c
    if (w <= 0 || h <= 0) return
    if (this.t.style === 'soft') {
      const g = c.createLinearGradient(0, y, 0, y + h)
      g.addColorStop(0, css(col, k * 1.07)); g.addColorStop(1, css(col, k * 0.9))
      c.fillStyle = g
      c.beginPath(); c.roundRect(x, y, w, h, Math.min(1.5, w / 3, h / 3)); c.fill()
      return
    }
    c.fillStyle = css(col, k)
    c.fillRect(x, y, w, h)
  }

  /** A rect with the theme's outline around it. */
  box(x: number, y: number, w: number, h: number, col: RGB, k = 1) {
    if (this.t.outline) {
      this.c.fillStyle = this.t.outline
      if (this.t.style === 'soft') { this.c.beginPath(); this.c.roundRect(x - 0.6, y - 0.6, w + 1.2, h + 1.2, 2); this.c.fill() }
      else this.c.fillRect(x - 1, y - 1, w + 2, h + 2)
    }
    this.rect(x, y, w, h, col, k)
  }

  circle(cx: number, cy: number, r: number, col: RGB, k = 1, outline = true) {
    const c = this.c
    if (this.t.style === 'soft') {
      if (outline && this.t.outline) { c.fillStyle = this.t.outline; c.beginPath(); c.arc(cx, cy, r + 0.6, 0, 7); c.fill() }
      const g = c.createRadialGradient(cx - r / 3, cy - r / 3, r / 6, cx, cy, r)
      g.addColorStop(0, css(col, k * 1.18)); g.addColorStop(1, css(col, k * 0.86))
      c.fillStyle = g; c.beginPath(); c.arc(cx, cy, r, 0, 7); c.fill()
      return
    }
    const rows = (rr: number, fill: string) => {
      c.fillStyle = fill
      for (let dy = -rr; dy <= rr; dy++) {
        const half = Math.round(Math.sqrt(Math.max(0, rr * rr - dy * dy)))
        c.fillRect(Math.round(cx - half), Math.round(cy + dy), half * 2, 1)
      }
    }
    if (outline && this.t.outline) rows(r + 1, this.t.outline)
    rows(r, css(col, k))
  }

  /** A triangle pointing up: gables, pediments, pointy hats. */
  tri(x: number, y: number, w: number, h: number, col: RGB, k = 1) {
    const c = this.c
    if (this.t.style === 'soft') {
      if (this.t.outline) { c.fillStyle = this.t.outline; c.beginPath(); c.moveTo(x - 0.8, y + h + 0.4); c.lineTo(x + w / 2, y - 0.8); c.lineTo(x + w + 0.8, y + h + 0.4); c.fill() }
      c.fillStyle = css(col, k); c.beginPath(); c.moveTo(x, y + h); c.lineTo(x + w / 2, y); c.lineTo(x + w, y + h); c.fill()
      return
    }
    for (let i = 0; i < h; i++) {
      const rw = Math.max(1, Math.round(w * (i + 1) / h))
      if (this.t.outline) { c.fillStyle = this.t.outline; c.fillRect(Math.round(x + (w - rw) / 2) - 1, y + i, rw + 2, 1) }
    }
    for (let i = 0; i < h; i++) {
      const rw = Math.max(1, Math.round(w * (i + 1) / h)) - (this.t.outline ? 0 : 0)
      c.fillStyle = css(col, k)
      c.fillRect(Math.round(x + (w - rw) / 2), y + i, rw, 1)
    }
  }

  shadow(cx: number, cy: number, rx: number, ry: number, a = 0.22) {
    const c = this.c
    c.fillStyle = `rgba(0,0,0,${a})`
    if (this.t.style === 'soft') { c.beginPath(); c.ellipse(cx, cy, rx, ry, 0, 0, 7); c.fill(); return }
    c.fillRect(Math.round(cx - rx), Math.round(cy - ry / 2), Math.round(rx * 2), Math.max(1, Math.round(ry)))
    c.fillRect(Math.round(cx - rx * 0.7), Math.round(cy - ry), Math.round(rx * 1.4), Math.max(1, Math.round(ry * 2)))
  }
}

// ---------- buildings (64×64 art px: four tiles square, standing on its bottom edge) ----------

export const BUILDING_PX = 64

function windows(p: Paint, x: number, y: number, cols: number, rows: number, w: number, h: number, gx: number, gy: number, col: RGB) {
  for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
    const wx = x + i * gx, wy = y + j * gy
    p.box(wx, wy, w, h, col)
    p.rect(wx, wy, Math.max(1, w / 3), h, [255, 255, 255], 0.9)  // glint
  }
}
const door = (p: Paint, x: number, y: number, w: number, h: number, col: RGB) => { p.box(x, y, w, h, col); p.rect(x + w - 2, y + h / 2, 1, 1, [240, 210, 120]) }
const roof = (p: Paint, x: number, y: number, w: number, h: number, col: RGB) => {
  p.box(x, y, w, h, col)
  for (let j = y + 3; j < y + h - 1; j += 4) p.rect(x, j, w, 1, col, 0.82)      // shingle rows
  p.rect(x, y + h - 2, w, 2, col, 0.66)                                          // eave
  p.rect(x, y, w, 1, col, 1.2)                                                   // ridge light
}
const bricks = (p: Paint, x: number, y: number, w: number, h: number, col: RGB) => {
  p.box(x, y, w, h, col)
  for (let j = y + 4; j < y + h; j += 5) p.rect(x, j, w, 1, col, 0.82)
  for (let j = y; j < y + h; j += 5) for (let i = x + ((j / 5) % 2 ? 3 : 6); i < x + w; i += 7) p.rect(i, j, 1, Math.min(4, y + h - j), col, 0.82)
}
const planks = (p: Paint, x: number, y: number, w: number, h: number, col: RGB) => {
  p.box(x, y, w, h, col)
  for (let i = x + 4; i < x + w; i += 5) p.rect(i, y, 1, h, col, 0.8)
}

export function drawBuilding(p: Paint, style: BuildingStyle, color: RGB) {
  const t = p.t
  p.shadow(32, 61, 30, 3)
  switch (style) {
    case 'cottage': {
      p.box(10, 34, 44, 25, t.wall)
      roof(p, 6, 12, 52, 24, color)
      p.box(44, 4, 7, 12, t.stone)
      door(p, 28, 44, 8, 15, t.wood)
      windows(p, 14, 40, 2, 1, 8, 8, 28, 0, t.glass)
      for (let i = 0; i < 5; i++) p.rect(13 + i * 2, 49, 1, 2, t.flowers[i % 3])
      break
    }
    case 'office': {
      p.box(8, 14, 48, 45, t.wall, 0.96)
      p.box(6, 9, 52, 6, color)
      windows(p, 12, 19, 4, 3, 7, 7, 11, 10, t.glass)
      door(p, 27, 48, 10, 11, t.glass)
      p.box(22, 42, 20, 4, color, 0.9)
      break
    }
    case 'studio': {
      p.box(6, 18, 52, 41, t.dark)
      p.box(4, 13, 56, 6, t.dark, 1.25)
      p.rect(6, 19, 52, 2, color, 1.25)                        // neon stripe
      p.box(10, 25, 44, 17, t.glass, 0.95)
      for (let i = 0; i < 4; i++) p.rect(12 + i * 11, 25, 1, 17, t.dark)
      p.rect(14, 27, 6, 1, [255, 255, 255]); p.rect(14, 29, 3, 1, [255, 255, 255])
      door(p, 28, 47, 9, 12, t.glass)
      p.box(49, 2, 2, 12, t.stone)
      break
    }
    case 'forge': {
      roof(p, 4, 12, 56, 22, t.wood)
      p.rect(4, 32, 56, 2, color)                              // trim in the agent's colour
      bricks(p, 8, 34, 48, 25, t.stone)
      p.box(42, 0, 10, 16, t.stone, 0.9)
      p.box(22, 43, 14, 16, [40, 26, 20])                      // the open forge (glow drawn live)
      p.box(48, 52, 9, 4, t.dark); p.box(50, 56, 5, 3, t.dark)  // anvil
      break
    }
    case 'library': {
      p.box(6, 30, 52, 27, t.wall)
      p.tri(4, 10, 56, 20, color)
      p.rect(24, 18, 16, 6, t.wall, 0.95)
      for (let i = 0; i < 5; i++) p.box(9 + i * 11, 31, 4, 25, [250, 246, 236])
      p.box(27, 41, 10, 15, t.dark)
      p.box(14, 57, 36, 3, t.stone, 1.1)
      break
    }
    case 'lab': {
      p.box(8, 32, 48, 27, [242, 244, 248])
      p.circle(32, 32, 18, t.glass, 0.95)
      p.rect(14, 30, 36, 4, color)
      p.rect(24, 18, 4, 3, [255, 255, 255])
      windows(p, 13, 40, 2, 1, 7, 7, 31, 0, t.glass)
      door(p, 27, 45, 10, 14, color)
      break
    }
    case 'observatory': {
      bricks(p, 14, 28, 36, 31, t.stone)
      p.circle(32, 26, 18, color)
      p.rect(30, 8, 4, 18, t.dark)
      p.box(36, 6, 14, 4, [200, 190, 160]); p.rect(48, 5, 3, 6, [200, 190, 160])  // telescope
      door(p, 27, 46, 10, 13, t.wood)
      break
    }
    case 'tavern': {
      p.box(6, 30, 52, 29, t.wall)
      for (let i = 6; i < 58; i += 13) p.rect(i, 30, 2, 29, t.wood, 0.8)
      p.rect(6, 42, 52, 2, t.wood, 0.8)
      roof(p, 3, 8, 58, 24, color)
      windows(p, 11, 34, 2, 1, 9, 7, 33, 0, t.light)
      door(p, 27, 45, 10, 14, t.wood)
      p.rect(52, 32, 6, 1, t.dark); p.box(53, 33, 5, 6, t.wood); p.rect(54, 35, 3, 2, [250, 210, 90])
      break
    }
    case 'tower': {
      bricks(p, 18, 10, 28, 49, t.stone)
      for (let i = 0; i < 4; i++) p.box(18 + i * 8, 5, 5, 5, t.stone)
      p.rect(18, 22, 28, 2, color)
      for (let j = 0; j < 2; j++) p.box(30, 28 + j * 9, 4, 6, t.dark)
      door(p, 27, 47, 10, 12, t.wood)
      p.box(31, -6, 1, 12, t.dark)                              // flag pole (flag drawn live)
      break
    }
    // ---- your tools ----
    case 'stable': {
      planks(p, 6, 28, 52, 31, t.wood)
      roof(p, 3, 8, 58, 22, [150, 60, 46])
      p.box(22, 38, 20, 21, [44, 30, 22])
      p.box(27, 40, 9, 8, [130, 86, 52]); p.rect(28, 44, 6, 7, [130, 86, 52]); p.rect(29, 42, 1, 1, t.dark)  // a horse
      p.rect(27, 39, 3, 2, [70, 46, 30])
      p.box(8, 48, 10, 10, [222, 190, 92]); p.box(46, 50, 10, 8, [222, 190, 92])                            // hay
      break
    }
    case 'barn': {
      planks(p, 6, 26, 52, 33, [178, 58, 46])
      roof(p, 3, 6, 58, 22, [96, 92, 100])
      p.box(20, 36, 24, 23, [178, 58, 46], 0.86)
      p.rect(20, 36, 24, 2, [244, 240, 230]); p.rect(20, 57, 24, 2, [244, 240, 230])
      for (let i = 0; i < 22; i++) { p.rect(21 + i, 37 + i, 2, 1, [244, 240, 230]); p.rect(42 - i, 37 + i, 2, 1, [244, 240, 230]) }
      break
    }
    case 'clocktower': {
      bricks(p, 18, 10, 28, 49, t.stone)
      p.tri(16, -6, 32, 16, [92, 74, 120])
      p.circle(32, 22, 8, [250, 246, 230])                     // clock face (hands drawn live)
      door(p, 27, 47, 10, 12, t.wood)
      break
    }
    case 'workshop': {
      planks(p, 6, 28, 52, 31, t.wood)
      p.box(4, 14, 56, 15, [120, 128, 140]); for (let i = 6; i < 60; i += 6) p.rect(i, 14, 1, 15, [90, 96, 108])
      p.box(10, 38, 20, 21, t.dark)
      windows(p, 38, 36, 1, 1, 14, 9, 0, 0, t.glass)
      p.box(36, 50, 18, 4, t.wood, 0.8)                        // workbench
      break
    }
    case 'archive': case 'vault': {
      bricks(p, 6, 26, 52, 33, style === 'vault' ? [120, 132, 150] : t.stone)
      p.box(4, 18, 56, 9, style === 'vault' ? [80, 94, 120] : [120, 90, 70])
      if (style === 'vault') { p.circle(32, 46, 11, [176, 184, 196]); p.circle(32, 46, 6, [120, 128, 140]); p.rect(31, 40, 2, 12, [90, 96, 108]) }
      else { p.box(25, 40, 14, 19, t.dark); p.box(14, 32, 36, 6, [244, 232, 200]); p.rect(16, 34, 32, 1, [150, 120, 90]) }
      break
    }
    case 'signal': {
      p.box(10, 40, 24, 19, t.wall); roof(p, 8, 32, 28, 9, [80, 110, 160])
      for (let j = 0; j < 5; j++) { p.rect(44 - j, 8 + j * 10, 1, 10, t.dark); p.rect(52 + j, 8 + j * 10, 1, 10, t.dark); p.rect(44 - j, 8 + j * 10, 9 + 2 * j, 1, t.dark) }
      door(p, 18, 47, 8, 12, t.wood)
      break
    }
    case 'well': {
      p.box(14, 6, 2, 34, t.wood); p.box(48, 6, 2, 34, t.wood)
      roof(p, 8, 2, 48, 12, [120, 80, 60])
      p.circle(32, 46, 15, t.stone)
      p.circle(32, 44, 10, [40, 70, 120], 1, false)
      p.box(29, 20, 6, 6, t.wood, 0.8)
      break
    }
  }
}

// ---------- what moves: drawn every frame on top of the cached building ----------

export function drawLive(p: Paint, style: BuildingStyle, color: RGB, now: number, busy: boolean) {
  const c = p.c
  const s = now / 1000
  if (style === 'forge') {
    const f = 0.65 + 0.35 * Math.sin(s * 9) * Math.sin(s * 4.3)
    c.fillStyle = `rgba(255,${120 + 60 * f | 0},40,${busy ? 0.95 : 0.6 * f})`; c.fillRect(24, 46, 10, 13)
    for (let i = 0; i < 3; i++) {                        // smoke
      const k = (s * 0.6 + i / 3) % 1
      c.fillStyle = `rgba(200,200,210,${0.55 * (1 - k)})`
      const r = 2 + k * 5
      if (p.t.style === 'soft') { c.beginPath(); c.arc(47 + Math.sin(k * 6 + i) * 3, -2 - k * 22, r, 0, 7); c.fill() }
      else c.fillRect(Math.round(45 + Math.sin(k * 6 + i) * 3), Math.round(-4 - k * 22), Math.round(r), Math.round(r))
    }
  }
  if (style === 'tower') {                                // a flag in the agent's colour
    for (let i = 0; i < 10; i++) {
      c.fillStyle = css(color, 1 - i * 0.02)
      c.fillRect(32 + i, -6 + Math.round(Math.sin(s * 5 - i * 0.6) * 1.2), 1, 6)
    }
  }
  if (style === 'studio' || style === 'signal') {         // a blinking light on the antenna
    const on = Math.sin(s * 4) > 0
    c.fillStyle = on ? (style === 'studio' ? css(color, 1.3) : 'rgb(255,80,80)') : 'rgba(80,80,80,0.6)'
    if (style === 'studio') c.fillRect(48, 0, 4, 3)
    else c.fillRect(46, 4, 5, 4)
  }
  if (style === 'clocktower') {                           // the actual time
    const d = new Date(), h = (d.getHours() % 12 + d.getMinutes() / 60) / 12, m = d.getMinutes() / 60
    c.strokeStyle = '#2a2430'; c.lineCap = 'round'
    c.lineWidth = 1.6; c.beginPath(); c.moveTo(32, 22); c.lineTo(32 + Math.sin(h * 6.283) * 4.5, 22 - Math.cos(h * 6.283) * 4.5); c.stroke()
    c.lineWidth = 1; c.beginPath(); c.moveTo(32, 22); c.lineTo(32 + Math.sin(m * 6.283) * 6.5, 22 - Math.cos(m * 6.283) * 6.5); c.stroke()
  }
  if (style === 'workshop') {                             // a turning gear
    c.save(); c.translate(20, 30); c.rotate(s * (busy ? 4 : 1))
    c.fillStyle = '#b8b0a0'; for (let i = 0; i < 8; i++) { c.rotate(Math.PI / 4); c.fillRect(-1.5, -7, 3, 3) }
    c.beginPath(); c.arc(0, 0, 5, 0, 7); c.fill(); c.fillStyle = '#5a5248'; c.beginPath(); c.arc(0, 0, 2, 0, 7); c.fill()
    c.restore()
  }
  if (busy && style !== 'forge') {                         // lights on while the agent works
    c.fillStyle = `rgba(255,214,110,${0.25 + 0.15 * Math.sin(s * 3)})`
    c.fillRect(8, 20, 48, 38)
  }
}

// ---------- trees ----------

export function drawTree(p: Paint, r: number) {
  const t = p.t, leaf = t.leaf[Math.floor(r * t.leaf.length)]
  p.shadow(8, 23, 7, 2)
  p.box(7, 15, 3, 9, t.trunk)
  p.circle(8, 10, 7, leaf)
  if (t.style === 'pixel') { p.rect(5, 6, 3, 2, leaf, 1.25) }
}

// ---------- NPCs: one per agent, wandering its yard ----------

export type NpcLook = { color: RGB; seed: number; role: BuildingStyle | 'player'; brain?: BrainLook }
export type NpcPose = { dir: 1 | -1; step: number; walking: boolean; bob: number; now?: number }

/** Feet at (0,0); about 12 wide and 20 tall. */
export function drawNpc(p: Paint, look: NpcLook, pose: NpcPose) {
  const t = p.t
  const skin = t.skin[look.seed % t.skin.length], hair = t.hair[(look.seed >>> 3) % t.hair.length]
  const pants = mix(t.dark, look.color, 0.25), shirt = look.color
  const lift = pose.walking ? (pose.step % 2 ? 1 : 0) : 0
  const y0 = -pose.bob, b = look.brain, now = pose.now ?? 0
  if (b && b.glow) drawAura(p, b, now, false)
  p.shadow(0, 0, 6, 2, 0.25)
  if (b?.satchel) p.box(-7, y0 - 11, b.satchel + 1, b.satchel + 3, [120, 80, 50])   // the context it carries
  // legs
  p.box(-3, y0 - 5 - lift, 2, 5 + lift, pants)
  p.box(1, y0 - 5 - (pose.walking ? 1 - lift : 0), 2, 5, pants)
  if (look.role === 'player') p.box(-5, y0 - 11, 10, 9, [190, 40, 50])   // the cape, behind
  // body and arms
  p.box(-4, y0 - 11, 8, 7, shirt)
  p.rect(-4, y0 - 6, 8, 1, shirt, 0.7)
  const swing = pose.walking ? (pose.step % 2 ? 1 : -1) : 0
  p.box(-5, y0 - 10 + swing, 1, 5, shirt, 0.85); p.box(4, y0 - 10 - swing, 1, 5, shirt, 0.85)
  p.rect(-5, y0 - 5 + swing, 1, 1, skin); p.rect(4, y0 - 5 - swing, 1, 1, skin)
  // head, hair, eyes
  if (t.style === 'soft') p.circle(0, y0 - 14, 3.6, skin)
  else p.box(-3, y0 - 17, 6, 6, skin)
  p.rect(-3, y0 - 18, 6, 2, hair); p.rect(pose.dir > 0 ? -3 : 2, y0 - 17, 1, 3, hair)
  p.rect(pose.dir > 0 ? 0 : -2, y0 - 15, 1, 1, [30, 24, 30]); p.rect(pose.dir > 0 ? 2 : 0, y0 - 15, 1, 1, [30, 24, 30])
  // what the job looks like
  switch (look.role) {
    case 'forge': p.rect(-4, y0 - 10, 8, 6, [70, 56, 50]); p.box(5, y0 - 12, 1, 6, t.wood); p.box(4, y0 - 13, 3, 2, [150, 150, 160]); break
    case 'library': p.rect(-3, y0 - 15, 2, 1, [40, 40, 50]); p.rect(1, y0 - 15, 2, 1, [40, 40, 50]); p.box(-7, y0 - 9, 3, 4, [160, 60, 60]); break
    case 'studio': p.rect(-4, y0 - 19, 8, 1, [40, 40, 50]); p.box(-5, y0 - 16, 2, 3, [40, 40, 50]); p.box(3, y0 - 16, 2, 3, [40, 40, 50]); break
    case 'lab': p.rect(-3, y0 - 16, 6, 2, [150, 220, 240]); p.rect(-4, y0 - 11, 8, 3, [245, 245, 250]); break
    case 'observatory': p.tri(-4, y0 - 26, 8, 8, [60, 60, 140]); p.rect(-1, y0 - 22, 1, 1, [250, 230, 120]); break
    case 'tower': p.rect(-3, y0 - 20, 6, 2, [240, 200, 60]); p.rect(-3, y0 - 21, 1, 1, [240, 200, 60]); p.rect(0, y0 - 21, 1, 1, [240, 200, 60]); p.rect(2, y0 - 21, 1, 1, [240, 200, 60]); break
    case 'tavern': p.rect(-3, y0 - 9, 6, 5, [245, 240, 230]); break
    case 'cottage': p.rect(-5, y0 - 18, 10, 1, [226, 196, 110]); p.rect(-3, y0 - 20, 6, 2, [226, 196, 110]); break
    case 'player':                                          // you: a cape and a feathered cap
      p.rect(-5, y0 - 18, 10, 2, [40, 90, 170]); p.rect(-3, y0 - 20, 6, 2, [40, 90, 170]); p.rect(4, y0 - 23, 1, 4, [240, 70, 70]); break
    default: p.rect(0, y0 - 11, 1, 4, [190, 50, 50]); break   // office: a tie
  }
  if (b) {
    if (b.trim) { p.rect(-4, y0 - 6, 8, 1, b.trim); p.rect(-2, y0 - 11, 4, 1, b.trim) }   // belt and collar: what it costs
    const hatted = look.role === 'observatory' || look.role === 'tower' || look.role === 'cottage' || look.role === 'studio'
    if (!hatted) switch (b.gear) {
      case 'feather': p.rect(-3, y0 - 18, 6, 1, b.aura); p.rect(2, y0 - 22, 1, 4, b.aura); p.rect(3, y0 - 23, 1, 2, b.aura, 1.2); break
      case 'cap': p.rect(-3, y0 - 17, 6, 1, b.aura); break
      case 'circlet': p.rect(-3, y0 - 17, 6, 1, b.trim ?? b.aura); p.rect(0, y0 - 17, 1, 1, b.aura, 1.2); break
      case 'crown':
        p.rect(-3, y0 - 20, 6, 2, b.trim ?? b.aura)
        for (const x of [-3, 0, 2]) p.rect(x, y0 - 21, 1, 1, b.trim ?? b.aura)
        p.rect(0, y0 - 19, 1, 1, [220, 60, 80]); break
      case 'goggles': p.rect(-3, y0 - 16, 6, 2, [60, 60, 70]); p.rect(-2, y0 - 16, 1, 1, b.aura, 1.2); p.rect(1, y0 - 16, 1, 1, b.aura, 1.2); break
    }
    if (b.glow) drawAura(p, b, now, true)
  }
}

/** Thinking, made visible: a glow at its feet behind it, and sparks rising off it in front. */
function drawAura(p: Paint, b: BrainLook, now: number, front: boolean) {
  const c = p.c
  if (!front) {
    const pulse = 0.75 + 0.25 * Math.sin(now / 450)
    c.fillStyle = css(b.aura, 1, 0.11 * b.glow * pulse)
    c.beginPath(); c.ellipse(0, -1, 6 + b.glow * 1.6, 2.5 + b.glow * 0.6, 0, 0, 7); c.fill()
    if (b.glow >= 3) {                                    // a column of light for the deep thinkers
      const g = c.createLinearGradient(0, 0, 0, -26)
      g.addColorStop(0, css(b.aura, 1, 0.07 * b.glow * pulse)); g.addColorStop(1, css(b.aura, 1, 0))
      c.fillStyle = g; c.fillRect(-7, -26, 14, 26)
    }
    return
  }
  for (let i = 0; i < b.glow; i++) {
    const ph = (now / 1400 + i / b.glow) % 1
    const x = Math.round(Math.sin(i * 2.3 + now / 500) * 6), y = Math.round(-4 - ph * 24)
    c.fillStyle = css(b.aura, 1.15, 1 - ph); c.fillRect(x, y, 1, 1)
  }
  if (b.glow >= 5) {                                      // thinking as hard as it can: a ring of light orbits it
    const a = now / 300
    for (let k = 0; k < 3; k++) {
      const t = a + k * 2.09, x = Math.round(Math.cos(t) * 8), y = Math.round(-9 + Math.sin(t) * 2.5)
      if ((Math.sin(t) > 0)) { c.fillStyle = css(b.aura, 1.2, 0.9); c.fillRect(x, y, 2, 2) }
    }
  }
}

/** A speech bubble over the NPC's head: working, waking up, or something wrong. */
export function drawBubble(p: Paint, kind: 'busy' | 'starting' | 'error' | 'ready', now: number) {
  const c = p.c
  const y = -30
  if (kind === 'ready') {
    c.fillStyle = `rgba(80,220,120,${0.6 + 0.4 * Math.sin(now / 300)})`; c.fillRect(-1, y + 4, 2, 2)
    return
  }
  p.box(-7, y - 4, 14, 9, kind === 'error' ? [250, 236, 236] : [255, 255, 255])
  p.rect(-1, y + 5, 2, 2, [255, 255, 255])
  if (kind === 'error') { p.rect(-1, y - 2, 2, 4, [210, 50, 50]); p.rect(-1, y + 3, 2, 1, [210, 50, 50]); return }
  const n = Math.floor(now / 300) % 4
  for (let i = 0; i < 3; i++) p.rect(-5 + i * 4, y, 2, 2, i < n ? [60, 60, 70] : [200, 200, 210])
}

/** Over a lead who has come to see you: a speech box with ? (a question, or a paused thread) or a letter (news). */
export function drawVisitBubble(p: Paint, kind: 'ask' | 'fyi', now: number) {
  const c = p.c
  const y = -38 + Math.round(Math.sin(now / 300) * 1.5)
  p.box(-8, y - 6, 16, 12, kind === 'ask' ? [255, 246, 214] : [255, 255, 255])
  p.rect(-2, y + 6, 4, 2, kind === 'ask' ? [255, 246, 214] : [255, 255, 255]); p.rect(-1, y + 8, 2, 1, kind === 'ask' ? [255, 246, 214] : [255, 255, 255])
  if (kind === 'ask') {
    c.fillStyle = '#b8862b'; c.font = '700 10px monospace'; c.textAlign = 'center'; c.textBaseline = 'middle'
    c.fillText('?', 0, y + 0.5); c.textBaseline = 'alphabetic'
  } else {
    p.rect(-5, y - 3, 10, 7, [236, 226, 204]); p.rect(-5, y - 3, 10, 1, [170, 150, 120])
    for (let i = 0; i < 5; i++) { p.rect(-5 + i, y - 2 + i * 0.6, 1, 1, [170, 150, 120]); p.rect(4 - i, y - 2 + i * 0.6, 1, 1, [170, 150, 120]) }
  }
}

// ---------- agents' houses, put together from their spec ----------

export type Anchors = { chimney?: [number, number]; flag?: [number, number]; antenna?: [number, number]; glow?: [number, number, number, number] }

/** 32 by 32: a tool's market stall in a team's courtyard: an awning in the app's colour and a sign board
 *  over it. The app's icon goes on the board (drawn live, so it stays sharp: see STALL_SIGN). */
export function drawToolStall(p: Paint, color: RGB) {
  p.shadow(16, 30, 14, 2)
  p.rect(4, 9, 2, 16, p.t.dark); p.rect(26, 9, 2, 16, p.t.dark)          // posts
  p.box(2, 19, 28, 10, p.t.wood)                                          // counter
  p.rect(3, 19, 26, 2, p.t.wood, 1.25)
  for (let i = 0; i < 7; i++) p.box(1 + i * 4.3, 4, 4.3, 6, i % 2 ? [250, 246, 236] : color)
  for (let i = 0; i < 7; i++) p.rect(1 + i * 4.3, 10, 4.3, 2, i % 2 ? [250, 246, 236] : color, 0.85)
  p.rect(15, -3, 2, 7, p.t.dark)                                          // the sign's post
  p.box(STALL_SIGN.x, STALL_SIGN.y, STALL_SIGN.w, STALL_SIGN.h, [250, 244, 228])
  p.rect(STALL_SIGN.x, STALL_SIGN.y + STALL_SIGN.h - 2, STALL_SIGN.w, 2, color)
}
/** 32 by 32: a colony's post office, in its courtyard beside the stalls: a little brick office with a
 *  roof in the colony's colour, a POST board over the door, and a pillar box by it. The box's flag and
 *  the letters waiting are drawn live (drawPostLive). */
export function drawPostOffice(p: Paint, color: RGB) {
  const t = p.t
  p.shadow(16, 30, 15, 2)
  bricks(p, 3, 12, 22, 17, [196, 172, 142])
  roof(p, 1, 2, 26, 11, color)
  p.box(5, 13, 18, 4, [250, 244, 228])                                    // the POST board
  for (const [x, w] of [[7, 3], [11, 3], [15, 3], [19, 2]] as const) p.rect(x, 14, w, 2, [150, 40, 40])
  door(p, 11, 19, 6, 10, t.wood)
  p.box(4, 20, 5, 4, t.glass); p.box(19, 20, 5, 4, t.glass)
  p.box(26, 18, 5, 11, [200, 46, 40])                                     // the pillar box
  p.rect(26, 17, 5, 2, [160, 30, 30]); p.rect(27, 21, 3, 1, [40, 20, 20])
}

/** The post office's live part: its box's flag, up while mail waits for the colony, and how many. */
export function drawPostLive(p: Paint, waiting: number, threads: number, now: number) {
  const c = p.c
  if (waiting > 0) {
    const wave = Math.round(Math.sin(now / 250))
    p.rect(30, 10, 1, 8, p.t.dark); p.rect(31, 10 + wave, 4, 3, [245, 200, 60])   // the flag
    c.fillStyle = '#c62f2a'; c.beginPath(); c.arc(4, 4, 6, 0, 7); c.fill()
    c.fillStyle = '#fff'; c.font = '700 8px monospace'; c.textAlign = 'center'; c.textBaseline = 'middle'
    c.fillText(String(Math.min(waiting, 9)), 4, 4.5); c.textBaseline = 'alphabetic'
  } else if (threads > 0) {                                               // nothing waiting, but its mail is going: a lit window
    c.fillStyle = `rgba(255,214,110,${0.35 + 0.15 * Math.sin(now / 400)})`; c.fillRect(4, 20, 5, 4); c.fillRect(19, 20, 5, 4)
  }
}

/** Where the icon board sits on a stall, from the stall's top-left (it pokes up into the roof room). */
export const STALL_SIGN = { x: 7, y: -17, w: 18, h: 16 }

/** Where each app's icon plate sits on a house's annex, from the sprite's top-left. */
export function annexSlots(s: HouseSpec): [number, number][] {
  const { body, annex, h } = houseSize(s)
  if (!annex) return []
  return s.tools.map((_, i) => {
    const col = annex > 16 ? i % 2 : 0, row = annex > 16 ? Math.floor(i / 2) : i
    return [body - 3 + 2 + col * 15, h - 24 + 1 + row * 11]
  })
}

/** Window rows: one per story; the ground floor leaves room for the door. */
function storyWindows(p: Paint, x: number, w: number, h: number, stories: number, col: RGB, spacing = 12, ww = 7, wh = 7) {
  const n = Math.max(1, Math.floor((w - 8) / spacing))
  const start = x + (w - (n - 1) * spacing - ww) / 2
  for (let k = 0; k < stories; k++) {
    const y = k === 0 ? h - 14 : h - 16 - 12 * k + 2
    for (let i = 0; i < n; i++) {
      const wx = Math.round(start + i * spacing)
      if (k === 0 && Math.abs(wx + ww / 2 - (x + w / 2)) < 9) continue      // the door
      p.box(wx, y, ww, wh, col)
      p.rect(wx, y, Math.max(1, Math.round(ww / 3)), wh, [255, 255, 255], 0.9)
    }
  }
}

export function drawHouse(p: Paint, s: HouseSpec): Anchors {
  const t = p.t, c = s.color
  const { body, annex, wall, roof: rh, w, h } = houseSize(s)
  const top = h - wall                       // where the walls start
  const a: Anchors = { glow: [2, top + 2, body - 4, wall - 4] }
  const mid = body / 2
  p.shadow(w / 2, h - 1, w / 2, 3)

  if (annex) {                               // the tools annex: one emblem per connection it may use
    const ax = body - 3, aw = annex + 3, ah = 24
    planks(p, ax, h - ah, aw, ah - 1, t.wood)
    p.box(ax - 1, h - ah - 5, aw + 2, 6, c, 0.7)
    for (const [x, y] of annexSlots(s)) p.box(x, y, 11, 10, [250, 244, 228])   // a plate for each app's icon
  }

  const door = (dw = 9, col: RGB = t.wood) => { p.box(Math.round(mid - dw / 2), h - 14, dw, 13, col); p.rect(Math.round(mid + dw / 2) - 2, h - 8, 1, 1, [240, 210, 120]) }
  const gable = (col: RGB) => roof(p, -2, top - rh, body + 4, rh + 2, col)

  switch (s.style) {
    case 'cottage':
      p.box(4, top, body - 8, wall - 1, t.wall)
      gable(c)
      p.box(Math.round(body * 0.68), top - rh - 6, 6, 12, t.stone); a.chimney = [Math.round(body * 0.68) + 3, top - rh - 6]
      storyWindows(p, 4, body - 8, h, s.stories, t.glass)
      door()
      for (let i = 0; i < Math.floor(body / 10); i++) p.rect(6 + i * 9, h - 4, 2, 2, t.flowers[i % 3])
      break
    case 'office':
      p.box(3, top, body - 6, wall - 1, t.wall, 0.96)
      p.box(1, top - 6, body - 2, 7, c)
      storyWindows(p, 3, body - 6, h, s.stories, t.glass, 9, 6, 7)
      door(10, t.glass)
      break
    case 'studio':
      p.box(2, top, body - 4, wall - 1, t.dark)
      p.box(0, top - 6, body, 7, t.dark, 1.25)
      p.rect(2, top + 1, body - 4, 2, c, 1.25)
      for (let k = 0; k < s.stories; k++) {
        const y = k === 0 ? h - 14 : h - 16 - 12 * k + 2
        p.box(6, y, body - 12, 8, t.glass, 0.95); p.rect(8, y + 1, 4, 1, [255, 255, 255])
      }
      door(9, t.glass)
      p.box(body - 10, top - 18, 2, 12, t.stone); a.antenna = [body - 9, top - 18]
      break
    case 'forge':
      roof(p, -2, top - rh, body + 4, rh + 2, t.wood)
      p.rect(-2, top, body + 4, 2, c)
      bricks(p, 3, top + 2, body - 6, wall - 3, t.stone)
      p.box(Math.round(body * 0.66), top - rh - 12, 10, 18, t.stone, 0.9); a.chimney = [Math.round(body * 0.66) + 5, top - rh - 12]
      p.box(Math.round(mid - 7), h - 16, 14, 15, [40, 26, 20]); a.glow = [Math.round(mid - 6), h - 13, 12, 12]
      p.box(body - 12, h - 9, 8, 4, t.dark); p.box(body - 10, h - 5, 4, 4, t.dark)
      storyWindows(p, 3, body - 6, h - 16, s.stories - 1, t.light)
      break
    case 'library': {
      p.box(2, top, body - 4, wall - 1, t.wall)
      p.tri(0, top - rh, body, rh, c); p.rect(Math.round(mid - 8), top - Math.round(rh * 0.45), 16, 4, t.wall, 0.95)
      const n = Math.max(3, Math.floor(body / 11))
      for (let i = 0; i < n; i++) p.box(Math.round(5 + i * (body - 14) / (n - 1)), top + 2, 4, wall - 4, [250, 246, 236])
      p.box(Math.round(mid - 5), h - 15, 10, 14, t.dark)
      p.box(8, h - 2, body - 16, 2, t.stone, 1.1)
      break
    }
    case 'lab':
      p.box(3, top, body - 6, wall - 1, [242, 244, 248])
      p.circle(mid, top + 1, Math.round(body * 0.3), t.glass, 0.95)
      p.rect(Math.round(mid - body * 0.32), top, Math.round(body * 0.64), 3, c)
      storyWindows(p, 3, body - 6, h, s.stories, t.glass)
      door(10, c)
      break
    case 'observatory':
      bricks(p, Math.round(body * 0.15), top, Math.round(body * 0.7), wall - 1, t.stone)
      p.circle(mid, top + 2, Math.round(body * 0.36), c)
      p.rect(Math.round(mid - 2), top + 2 - Math.round(body * 0.36), 4, Math.round(body * 0.36), t.dark)
      p.box(Math.round(mid + 4), top - Math.round(body * 0.34), 14, 4, [200, 190, 160])
      door()
      break
    case 'tavern':
      p.box(2, top, body - 4, wall - 1, t.wall)
      for (let i = 2; i < body - 2; i += 13) p.rect(i, top, 2, wall - 1, t.wood, 0.8)
      for (let k = 1; k < s.stories + 1; k++) p.rect(2, h - 4 - 12 * k, body - 4, 2, t.wood, 0.8)
      gable(c)
      storyWindows(p, 2, body - 4, h, s.stories, t.light)
      door()
      p.rect(body - 8, top + 3, 6, 1, t.dark); p.box(body - 7, top + 4, 5, 6, t.wood); p.rect(body - 6, top + 6, 3, 2, [250, 210, 90])
      break
    case 'tower': {
      const tx = Math.round(body * 0.22), tw = Math.round(body * 0.56)
      if (body >= 64) { bricks(p, 2, h - 26, body - 4, 25, t.stone); p.rect(2, h - 27, body - 4, 2, c) }   // the great hall
      bricks(p, tx, top - rh, tw, wall + rh - 1, t.stone)
      for (let i = 0; i < Math.floor(tw / 7); i++) p.box(tx + i * 7, top - rh - 5, 4, 5, t.stone)
      p.rect(tx, top + 6, tw, 2, c)
      for (let k = 0; k < s.stories + 1; k++) p.box(Math.round(mid - 2), top + 12 + k * 10, 4, 6, t.dark)
      door(10)
      p.box(Math.round(mid), top - rh - 17, 1, 12, t.dark); a.flag = [Math.round(mid) + 1, top - rh - 17]
      break
    }
  }
  if (s.banner && !a.flag) { p.box(body - 6, top - rh - 12, 1, 12, t.dark); a.flag = [body - 5, top - rh - 12] }
  return a
}


/** What moves on a house: smoke, flags, a blinking antenna, the forge's fire, lights when it works. */
export function drawHouseLive(p: Paint, s: HouseSpec, a: Anchors, now: number, busy: boolean) {
  const c = p.c, sec = now / 1000
  if (a.chimney && (s.style === 'forge' || busy)) {
    for (let i = 0; i < 3; i++) {
      const k = (sec * 0.6 + i / 3) % 1, r = 2 + k * 5
      c.fillStyle = `rgba(200,200,210,${0.55 * (1 - k)})`
      const x = a.chimney[0] + Math.sin(k * 6 + i) * 3, y = a.chimney[1] - 2 - k * 22
      if (p.t.style === 'soft') { c.beginPath(); c.arc(x, y, r, 0, 7); c.fill() } else c.fillRect(Math.round(x - r / 2), Math.round(y), Math.round(r), Math.round(r))
    }
  }
  if (s.style === 'forge' && a.glow) {
    const f = 0.65 + 0.35 * Math.sin(sec * 9) * Math.sin(sec * 4.3)
    c.fillStyle = `rgba(255,${120 + 60 * f | 0},40,${busy ? 0.95 : 0.6 * f})`; c.fillRect(...a.glow)
  } else if (busy && a.glow) {
    c.fillStyle = `rgba(255,214,110,${0.22 + 0.12 * Math.sin(sec * 3)})`; c.fillRect(...a.glow)
  }
  if (a.flag) for (let i = 0; i < 10; i++) {
    c.fillStyle = css(s.color, 1 - i * 0.02)
    c.fillRect(a.flag[0] + i, a.flag[1] + Math.round(Math.sin(sec * 5 - i * 0.6) * 1.2), 1, 6)
  }
  if (a.antenna) { c.fillStyle = Math.sin(sec * 4) > 0 ? css(s.color, 1.3) : 'rgba(80,80,80,0.6)'; c.fillRect(a.antenna[0] - 1, a.antenna[1] - 3, 4, 3) }
}

// ---------- the countryside and the square (16 art px wide, standing on their bottom edge) ----------

export function drawBush(p: Paint, r: number) {
  const leaf = p.t.leaf[Math.floor(r * p.t.leaf.length)]
  p.shadow(8, 14, 6, 1.5)
  p.circle(5, 10, 4, leaf); p.circle(11, 10, 4, leaf); p.circle(8, 7, 4, leaf, 1.08)
  if (r > 0.6) { p.rect(6, 6, 1, 1, [230, 60, 70]); p.rect(10, 9, 1, 1, [230, 60, 70]) }   // berries
}

export function drawRock(p: Paint, r: number) {
  p.shadow(8, 14, 6, 1.5)
  p.box(3, 8, 10, 6, p.t.stone, 0.95); p.box(5, 6, 6, 3, p.t.stone, 1.08)
  if (r > 0.5) p.rect(4, 9, 3, 1, p.t.stone, 1.2)
}

export function drawFlowers(p: Paint, r: number) {
  const f = p.t.flowers
  for (let i = 0; i < 5; i++) {
    const x = 2 + Math.floor(hash(i, r * 99) * 12), y = 6 + Math.floor(hash(r * 77, i) * 8)
    p.rect(x, y + 1, 1, 2, p.t.leaf[0]); p.rect(x, y, 1, 1, f[(i + Math.floor(r * 3)) % f.length])
  }
}

export function drawLamp(p: Paint) {
  p.shadow(8, 23, 3, 1)
  p.box(7, 6, 2, 17, p.t.dark); p.box(5, 2, 6, 5, p.t.dark); p.rect(6, 3, 4, 3, p.t.light)
}

export function drawBench(p: Paint) {
  p.shadow(8, 14, 7, 1.5)
  p.box(2, 6, 12, 2, p.t.wood, 1.1); p.box(2, 9, 12, 2, p.t.wood); p.rect(3, 11, 1, 3, p.t.dark); p.rect(12, 11, 1, 3, p.t.dark)
}

export function drawStall(p: Paint, r: number) {
  const cols: RGB[] = [[220, 70, 70], [70, 130, 220], [240, 180, 60], [90, 170, 100]]
  const c = cols[Math.floor(r * cols.length)]
  p.shadow(8, 23, 8, 1.5)
  p.box(1, 14, 14, 8, p.t.wood)
  for (let i = 0; i < 4; i++) p.rect(2 + i * 3, 15, 2, 2, p.t.flowers[i % p.t.flowers.length])
  p.rect(1, 6, 1, 8, p.t.dark); p.rect(14, 6, 1, 8, p.t.dark)
  for (let i = 0; i < 4; i++) p.box(i * 4, 3, 4, 4, i % 2 ? [250, 246, 236] : c)
}

export function drawHay(p: Paint) {
  p.shadow(8, 14, 6, 1.5)
  p.box(3, 7, 10, 7, [222, 190, 92]); p.rect(3, 9, 10, 1, [190, 156, 70]); p.rect(3, 12, 10, 1, [190, 156, 70])
}

export function drawSignpost(p: Paint) {
  p.shadow(8, 23, 4, 1)
  p.box(7, 8, 2, 15, p.t.wood); p.box(1, 4, 14, 6, p.t.wood, 1.2)
}

/** 48 wide, 32 tall: a round basin with a jet that sparkles. */
export function drawFountain(p: Paint, now: number) {
  const c = p.c
  p.shadow(24, 29, 22, 3)
  p.circle(24, 22, 16, p.t.stone, 1.05)
  p.circle(24, 21, 13, p.t.water, 1.05, false)
  p.box(22, 8, 4, 14, p.t.stone, 1.15)
  const s = now / 1000
  for (let i = 0; i < 8; i++) {                       // the jet falling back in arcs
    const k = (s * 0.9 + i / 8) % 1, side = i % 2 ? 1 : -1
    const x = 24 + side * k * 9, y = 7 - Math.sin(k * Math.PI) * 6 + k * 12
    c.fillStyle = `rgba(200,230,255,${0.9 - k * 0.5})`
    c.fillRect(Math.round(x), Math.round(y), 2, 2)
  }
  for (let i = 0; i < 3; i++) {                       // ripples
    const k = (s * 0.5 + i / 3) % 1
    c.strokeStyle = `rgba(255,255,255,${0.5 * (1 - k)})`; c.lineWidth = 1
    c.beginPath(); c.ellipse(24, 21, 3 + k * 9, 1.5 + k * 4, 0, 0, 7); c.stroke()
  }
}

// ---------- couriers: how an app's work travels to an agent ----------
// Drawn facing right with the ground at y = 0; the caller flips them for left.

export type Vehicle = 'horse' | 'cart' | 'boat'

export function drawHorse(p: Paint, color: RGB, step: number, rider = true) {
  const coat: RGB = [128, 84, 52], dark: RGB = [70, 46, 30]
  const k = step % 2
  p.shadow(0, 0, 9, 2)
  p.box(-7, -6 - k, 2, 6 + k, dark); p.box(-4, -6 + k, 2, 6 - k, dark)          // legs, trotting
  p.box(3, -6 + k, 2, 6 - k, dark); p.box(6, -6 - k, 2, 6 + k, dark)
  p.box(-8, -12, 16, 7, coat)                                                   // body
  p.box(6, -17, 4, 8, coat); p.box(8, -19, 6, 4, coat)                          // neck, head
  p.rect(12, -18, 1, 1, [20, 16, 16]); p.rect(6, -18, 2, 6, dark)               // eye, mane
  p.rect(-10, -12 + k, 2, 6, dark)                                              // tail
  if (!rider) return
  p.box(-4, -14, 7, 4, color)                                                   // saddlebag in the app's colour
  p.box(-2, -22, 5, 8, [60, 90, 150])                                           // rider
  p.box(-2, -26, 5, 4, p.t.skin[1])
  p.rect(-3, -27, 7, 2, [90, 60, 40])                                           // hat brim
}

export function drawCart(p: Paint, color: RGB, step: number) {
  p.c.save(); p.c.translate(7, 0); drawHorse(p, color, step, false); p.c.restore()
  p.box(-16, -11, 14, 7, p.t.wood)                                              // the cart
  p.box(-15, -15, 12, 4, color, 0.9)                                            // its load
  p.circle(-13, -3, 3, [60, 44, 32]); p.circle(-5, -3, 3, [60, 44, 32])
  p.rect(-2, -9, 4, 1, p.t.dark)
}

export function drawBoat(p: Paint, color: RGB, now: number) {
  const bob = Math.round(Math.sin(now / 400) * 1)
  p.c.fillStyle = 'rgba(255,255,255,0.5)'; p.c.fillRect(-14, 1, 4, 1); p.c.fillRect(-18, 2, 3, 1)   // wake
  p.box(-11, -4 + bob, 22, 5, p.t.wood)                                         // hull
  p.rect(-9, -1 + bob, 18, 1, p.t.wood, 0.75)
  p.box(-1, -22 + bob, 2, 18, p.t.dark)                                         // mast
  p.tri(1, -21 + bob, 10, 15, color)                                            // sail in the app's colour
  p.rect(-1, -24 + bob, 5, 2, [230, 70, 70])                                    // pennant
}
