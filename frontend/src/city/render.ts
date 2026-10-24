// Draws a Layout as a 2D top-down game world, with you in it. No framework: one
// requestAnimationFrame loop. The ground and every building are drawn once into offscreen canvases
// (per theme); each frame copies those, then draws what moves: you, the NPCs, smoke, flags.
//
// You: W A S D or the arrow keys (Shift runs), or click/tap the ground to walk there. Walk up to an
// agent and press E to talk to it. Click a building to open it (and walk to its door).
// A colony with a question or news for you sends its lead: it walks to the square and waits there with
// a speech box (setMail); click it, or walk up and press E, to read it (onVisit). Once you've answered,
// it walks home.
// The mayor has no house: it walks a step behind you everywhere (setCompanion). Press M or click it to talk.
// In move mode (setEditing) you drag buildings instead: onMove says where one was dropped.
// The Office look doesn't use the map at all (rooms.tsx): App hides it and pauses it (setPaused).

import type { MailVisit as Visit, PostCount, RunStatus } from '../api'
import { Paint, css, drawBench, drawBoat, drawBubble, drawBuilding, drawBush, drawCart, drawFlowers, drawFountain, drawHay, drawHorse, drawHouse,
  drawHouseLive, drawLamp, drawLive, drawNpc, drawPostLive, drawPostOffice, drawRock, drawSignpost, drawStall, drawToolStall, drawTree, drawVisitBubble, annexSlots, STALL_SIGN, hash, type Anchors, type NpcPose, type Vehicle } from './sprites'
import { Ground, STATUS_COLOR, T, meetingSpot, noise, route, seaLane, toSquare, whyNot, type Decor, type Layout, type Rect, type Thing, type Wire } from './layout'
import { EMOJI_FONT, type BuildingStyle } from './kinds'
import { THEMES, type Theme, type ThemeName } from './themes'
import { BAR_H, MAX_ZOOM, MIN_ZOOM, PHONE_BP, reduceMotion } from '../ui-constants'

const PAD = 28                       // room above a building's sprite for chimneys, flags, smoke
const SPEED = 4.2                    // tiles per second (Shift: faster)
const REACH = 1.8                    // how close you need to be to talk

type Pt = [number, number]
const DECOR_SIZE: Record<Decor['kind'], [number, number]> = {
  tree: [16, 24], bush: [16, 16], rock: [16, 16], flowers: [16, 16], lamp: [16, 24], bench: [16, 16], stall: [16, 24], hay: [16, 16], sign: [16, 24], fountain: [48, 32],
}
type Walker = { x: number; y: number; tx: number; ty: number; wait: number; dir: 1 | -1; dist: number
  trip?: 'going' | 'there' | 'back'; path?: Pt[] }       // a lead on its way to see you, waiting in the square, or going home

type Player = Walker & { target: Pt | null; moving: boolean }
type Courier = { vehicle: Vehicle; pts: Pt[]; seg: number; along: number; speed: number; color: [number, number, number]; live: boolean; dist: number; dir: 1 | -1 }
type Item = { y: number; draw: () => void }
type Chunk = { cv: HTMLCanvasElement; x: number; y: number; w: number; h: number }   // a piece of the ground, in tiles
const CHUNK = 32                     // tiles per ground chunk: 32 × 16 px × res 3 = 1536 px, well under any canvas limit

// how each kind of app's work travels across the courtyard: mail and calendar by rider, the rest by cart
const VEHICLE: Partial<Record<BuildingStyle, Vehicle>> = { stable: 'horse', clocktower: 'horse' }
const CARGO: Partial<Record<BuildingStyle, [number, number, number]>> = {
  stable: [200, 60, 60], clocktower: [240, 200, 80], workshop: [90, 90, 110], archive: [230, 220, 190],
  signal: [80, 140, 220], well: [70, 130, 200], barn: [180, 60, 50],
}

export class CityView {
  private ctx: CanvasRenderingContext2D
  private canvas: HTMLCanvasElement
  private L: Layout | null = null
  private theme: Theme = THEMES.retro
  private paused = false
  private view = { x: 0, y: 0, zoom: 2 }
  private selected: string | null = null
  private drag: { x: number; y: number; vx: number; vy: number; moved: boolean; id: number } | null = null
  private raf = 0
  private last = 0
  private ground: Chunk[] = []
  private sprites = new Map<string, { cv: HTMLCanvasElement; anchors?: Anchors }>()
  private items: Item[] = []           // reused every frame: what stands up, sorted back to front
  private pointers = new Map<number, Pt>()   // touches down right now, for pinching
  private pinch: { d: number; zoom: number; mid: Pt } | null = null
  private inputOn = true               // false while a modal or panel owns the keyboard
  private walkers = new Map<string, Walker>()
  private visits = new Map<number, Visit>()       // agent id -> why it has come
  private visitOrder: number[] = []               // the visitors left to right: their labels take turns high and low
  private companion: { id: number; name: string; look: Parameters<typeof drawNpc>[1]; w: Walker } | null = null   // the mayor
  private posts = new Map<number, PostCount>()    // a colony lead's id -> its post office's counts
  private status = new Map<number, RunStatus | null>()
  private keys = new Set<string>()
  private player: Player | null = null
  private playerName = 'you'
  private near: Thing | null = null
  private follow = false
  private bottomInset = 0
  private sideInsets: [number, number] = [0, 0]
  private cam: Pt | null = null
  private couriers: Courier[] = []
  private nextTrip = 0
  private editing = false
  private carry: { t: Thing; dx: number; dy: number; x: number; y: number; ok: boolean; why?: string; id: number } | null = null   // a building being moved
  onSelect: (t: Thing | null) => void = () => {}
  onMove: (t: Thing, x: number, y: number) => void = () => {}
  onVisit: (agentId: number) => void = () => {}
  onCompanion: () => void = () => {}

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas
    this.ctx = canvas.getContext('2d')!
    this.resize()
    canvas.addEventListener('pointerdown', this.down)
    window.addEventListener('pointermove', this.move)
    window.addEventListener('pointerup', this.up)
    window.addEventListener('pointercancel', this.up)
    canvas.addEventListener('wheel', this.wheel, { passive: false })
    window.addEventListener('resize', this.resize)
    window.addEventListener('keydown', this.keydown)
    window.addEventListener('keyup', this.keyup)
    window.addEventListener('blur', this.blur)
    this.raf = requestAnimationFrame(this.frame)
  }

  destroy() {
    cancelAnimationFrame(this.raf)
    window.removeEventListener('pointermove', this.move)
    window.removeEventListener('pointerup', this.up)
    window.removeEventListener('pointercancel', this.up)
    window.removeEventListener('resize', this.resize)
    window.removeEventListener('keydown', this.keydown)
    window.removeEventListener('keyup', this.keyup)
    window.removeEventListener('blur', this.blur)
  }

  /** Stop drawing while something else covers the map (the Office's rooms), and pick up again after. */
  setPaused(paused: boolean) { this.paused = paused }

  setTheme(name: ThemeName) {
    if (this.theme.name === name) return
    this.theme = THEMES[name]
    this.sprites.clear()
    if (this.L) this.ground = this.paintGround(this.L)
  }

  setLayout(L: Layout, refit: boolean) {
    const firstTime = !this.L
    if (this.L) {                // the island grew or shrank on one side: keep the world still on screen
      const dx = L.origin[0] - this.L.origin[0], dy = L.origin[1] - this.L.origin[1]
      if (dx || dy) {
        this.view.x -= dx * T * this.view.zoom; this.view.y -= dy * T * this.view.zoom
        if (this.cam) this.cam = [this.cam[0] - dx * T * this.view.zoom, this.cam[1] - dy * T * this.view.zoom]
        if (this.player) { this.player.x += dx; this.player.y += dy; this.player.target = null }
        for (const w of this.walkers.values()) { w.x += dx; w.y += dy; w.tx += dx; w.ty += dy }
        this.couriers = []
      }
    }
    this.L = L
    // sprites of buildings still on the map are kept (drawing them again is the slow part); the rest go
    const keep = new Set<string>()
    for (const t of L.things) keep.add(this.spriteKey(t))
    for (const d of L.decor) keep.add(this.decorKey(d))
    for (const k of this.sprites.keys()) if (!keep.has(k)) this.sprites.delete(k)
    this.ground = this.paintGround(L)
    for (const t of L.things) if (t.kind === 'agent' && t.npc) this.status.set(t.id, t.npc.status)
    const [W, H] = L.grid
    if (!this.player || this.player.x > W - 1 || this.player.y > H - 1 || this.collides(this.player.x, this.player.y)) {
      this.player = { x: L.spawn[0], y: L.spawn[1], tx: 0, ty: 0, wait: 0, dir: 1, dist: 0, target: null, moving: false }
    }
    if (firstTime || refit) this.fit()
    this.planVisits()
  }

  /** The mayor, who walks beside you (null: you have none). */
  setCompanion(c: { id: number; name: string; look: Parameters<typeof drawNpc>[1] } | null) {
    if (!c) { this.companion = null; return }
    const p = this.player
    const w = this.companion?.w ?? { x: (p?.x ?? 0) - 1.2, y: (p?.y ?? 0) + 0.3, tx: 0, ty: 0, wait: 0, dir: 1 as const, dist: 0 }
    this.companion = { ...c, w }
  }

  /** A step behind you, on the side you came from; it hurries when you run, and catches up if you go far. */
  private stepCompanion(dt: number) {
    const m = this.companion, p = this.player
    if (!m || !p) return
    const w = m.w, tx = p.x - p.dir * 1.15, ty = p.y + 0.35
    const dx = tx - w.x, dy = ty - w.y, d = Math.hypot(dx, dy)
    if (d > 9) { w.x = tx; w.y = ty; return }                      // you went far (a click across town): it's there
    w.tx = tx; w.ty = ty
    if (d < 0.25) { if (!p.moving) w.dir = p.x >= w.x ? 1 : -1; return }
    const v = Math.min(d, Math.max(SPEED * 0.8, d * 3) * dt)
    w.x += dx / d * v; w.y += dy / d * v; w.dist += v
    if (Math.abs(dx) > 0.02) w.dir = dx > 0 ? 1 : -1
  }

  /** Mail, from /api/mail/town: who comes to see you, and how full each post office is. */
  setMail(visits: Visit[], posts: Record<string, PostCount>) {
    this.posts = new Map(Object.entries(posts).map(([k, v]) => [Number(k), v]))
    this.visits = new Map(visits.map(v => [v.agent_id, v]))
    this.planVisits()
  }

  /** Send each visitor to its spot in the square (they stand in a row, so the spots move as they come
   *  and go), and the ones nobody is waiting on any more back home. */
  private planVisits() {
    const L = this.L
    if (!L) return
    const coming = L.things.filter(t => t.kind === 'agent' && t.npc && this.visits.has(t.id))
    this.visitOrder = coming.map(t => t.id)
    coming.forEach((t, i) => {
      const w = this.walker(t), spot = meetingSpot(L, i, coming.length)
      if (w.trip === 'going' && w.path?.length) w.path[w.path.length - 1] = spot
      else if (w.trip === 'there') { w.path = [spot]; w.trip = 'going' }
      else { w.path = [[w.x, w.y], ...toSquare(L, t, spot)]; w.trip = 'going' }
    })
    for (const t of L.things) {
      const w = t.npc && !this.visits.has(t.id) ? this.walkers.get(t.key) : undefined
      if (w && (w.trip === 'going' || w.trip === 'there')) { w.path = toSquare(L, t, [w.x, w.y]).reverse(); w.trip = 'back' }
    }
  }

  setPlayerName(name: string) { this.playerName = name }
  /** A chat's run changed state: the NPC walks to its door to work, or wanders again. */
  setAgentStatus(agentId: number, s: RunStatus | null) { this.status.set(agentId, s) }
  /** Everyone's state at once (from /api/runs/active): agents not listed are asleep. */
  setStatuses(awake: { agent_id: number; status: RunStatus }[]) {
    const on = new Map(awake.map(a => [a.agent_id, a.status]))
    for (const t of this.L?.things ?? []) if (t.kind === 'agent') this.status.set(t.id, on.get(t.id) ?? null)
  }

  /** An agent just used an app's tool (mcp__<server>__…): send that app's courier to it, now. */
  sendCourier(agentId: number, server: string) {
    const w = this.L?.wires.find(x => !x.team && x.to.id === agentId && x.to.kind === 'agent' && x.from.server === server)
    if (w) this.spawn(w, true)
  }

  private spawn(w: Wire, live: boolean) {
    const L = this.L!
    const vehicle = VEHICLE[w.from.style] ?? 'cart'
    let pts: Pt[]
    if (vehicle === 'boat') {                          // round the island by sea, the short way
      const lane = seaLane(L), ring: Pt[] = []
      for (let i = 1; i < lane.length; i++) {
        const [a, b] = [lane[i - 1], lane[i]], n = Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]))
        for (let j = 0; j < n; j++) ring.push([a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n])
      }
      const near = (p: Pt) => ring.reduce((bi, q, i) => Math.hypot(q[0] - p[0], q[1] - p[1]) < Math.hypot(ring[bi][0] - p[0], ring[bi][1] - p[1]) ? i : bi, 0)
      const i = near(w.from.door), j = near(w.to.door), n = ring.length
      const fwd = (j - i + n) % n, back = (i - j + n) % n
      pts = []
      for (let k = 0; k <= Math.min(fwd, back); k++) pts.push(ring[(i + (fwd <= back ? k : -k) + n) % n])
    } else pts = route(L, w.from, w.to)
    const tiles = vehicle === 'boat' ? 2.2 : vehicle === 'cart' ? 1.8 : 2.6
    this.couriers.push({ vehicle, pts: pts.map(([x, y]) => [x * T, y * T] as Pt), seg: 1, along: 0,
      speed: tiles * T * (live ? 2.4 : 1), color: CARGO[w.from.style] ?? [180, 140, 90], live, dist: 0, dir: 1 })
  }

  private stepCouriers(dt: number, now: number) {
    const tools = this.L!.wires.filter(w => !w.team)
    if (tools.length && !reduceMotion() && now > this.nextTrip && this.couriers.filter(c => !c.live).length < Math.min(5, tools.length)) {
      this.spawn(tools[Math.floor(Math.random() * tools.length)], false)
      this.nextTrip = now + 5000 + Math.random() * 9000          // now and then, so the roads feel used
    }
    for (const c of this.couriers) {
      let left = c.speed * dt
      while (left > 0 && c.seg < c.pts.length) {
        const [a, b] = [c.pts[c.seg - 1], c.pts[c.seg]]
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]), rest = len - c.along
        if (Math.abs(b[0] - a[0]) > 0.5) c.dir = b[0] > a[0] ? 1 : -1
        if (left < rest) { c.along += left; c.dist += left; left = 0 }
        else { left -= rest; c.dist += rest; c.seg++; c.along = 0 }
      }
    }
    this.couriers = this.couriers.filter(c => c.seg < c.pts.length)
  }

  private courierAt(c: Courier): Pt {
    const [a, b] = [c.pts[c.seg - 1], c.pts[c.seg]]
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
    return [a[0] + (b[0] - a[0]) * c.along / len, a[1] + (b[1] - a[1]) * c.along / len]
  }
  setSelected(key: string | null) { this.selected = key }
  /** Move mode: dragging a building moves it instead of panning the map. */
  setEditing(on: boolean) { this.editing = on; this.carry = null; if (this.player) this.player.target = null }
  /** Off while a modal, a setup screen or the caretaker owns the keyboard: keys don't walk or talk. */
  setInputEnabled(on: boolean) { this.inputOn = on; if (!on) this.keys.clear() }
  setBottomInset(px: number) { this.bottomInset = px }
  setSideInsets(left: number, right: number) { this.sideInsets = [left, right] }

  private center(): Pt {
    const [left, right] = this.sideInsets
    return [(left + innerWidth - right) / 2, (BAR_H + innerHeight - this.bottomInset) / 2]
  }

  /** The open space: below the bar, above the card, between the side panels. */
  private open(): Rect {
    const [left, right] = this.sideInsets
    return { x: left, y: BAR_H, w: innerWidth - left - right, h: innerHeight - BAR_H - this.bottomInset }
  }

  /** As far out as you can zoom: the whole island, with a little sea round it. */
  private minZoom(): number {
    if (!this.L) return MIN_ZOOM
    const [W, H] = this.L.grid, o = this.open()
    return Math.min(MAX_ZOOM, 0.85 * Math.min(o.w / (W * T), o.h / (H * T)))
  }

  /** Where the view may sit at zoom z: an island smaller than the open space stays in its middle; a
   *  bigger one can be dragged about, but never so far that its edge leaves the edge of the screen. */
  private bounded(x: number, y: number, z: number): Pt {
    if (!this.L) return [x, y]
    const [W, H] = this.L.grid, o = this.open()
    const axis = (v: number, start: number, span: number, size: number) =>
      size <= span ? start + (span - size) / 2 : Math.min(start, Math.max(start + span - size, v))
    return [axis(x, o.x, o.w, W * T * z), axis(y, o.y, o.h, H * T * z)]
  }

  /** Glide so this thing sits in the middle of the open space: above the card, between the side panels. */
  focusOn(key: string) {
    const t = this.L?.things.find(x => x.key === key)
    if (!t) return
    if (this.view.zoom < 2) this.view.zoom = 2
    const [cx, cy] = this.center()
    this.follow = false
    this.cam = [cx - (t.x + t.w / 2) * T * this.view.zoom, cy - (t.y + t.h / 2 + 1) * T * this.view.zoom]
  }

  /** The whole island if it fits at a readable size, else (a big town on a laptop) your own blocks. On a
   *  phone it's always the whole island, as small as it must be: names stay readable (they're drawn in
   *  screen pixels), and a pinch zooms in. */
  fit = () => {
    if (!this.L) return
    const [W, H] = this.L.grid
    const availH = innerHeight - BAR_H - this.bottomInset
    let r: Rect = { x: 0, y: 0, w: W, h: H }
    const phone = innerWidth <= PHONE_BP
    if (!phone && Math.min((innerWidth - 24) / (W * T), availH / (H * T)) < 0.4) r = this.L.home
    this.follow = false; this.cam = null
    this.view.zoom = Math.max(MIN_ZOOM, Math.min(3, (innerWidth - 24) / (r.w * T), availH / (r.h * T)))
    this.view.x = (innerWidth - r.w * T * this.view.zoom) / 2 - r.x * T * this.view.zoom
    this.view.y = BAR_H + (availH - r.h * T * this.view.zoom) / 2 - r.y * T * this.view.zoom
  }

  private resize = () => {
    const dpr = window.devicePixelRatio || 1
    this.canvas.width = innerWidth * dpr
    this.canvas.height = innerHeight * dpr
  }

  // ---------- you: keys, collisions, talking ----------

  private typing(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null
    return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
  }

  private keydown = (e: KeyboardEvent) => {
    if (!this.inputOn || this.typing(e) || e.metaKey || e.ctrlKey || e.altKey) return
    // Enter on a focused button presses the button, not the nearest door; a dialog on screen owns the keys
    const el = e.target as HTMLElement | null
    if (el?.closest?.('button, a, [role=dialog][aria-modal]') || document.querySelector('.backdrop')) return
    const k = e.key.toLowerCase()
    if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift'].includes(k)) {
      this.keys.add(k)
      if (k.startsWith('arrow')) e.preventDefault()
    }
    if (k === 'm' && this.companion && !e.repeat && !this.editing) { this.onCompanion(); e.preventDefault() }
    if ((k === 'e' || k === 'enter') && this.near && !e.repeat && !this.editing) {
      if (this.near.kind === 'agent' && this.visits.has(this.near.id) && this.walkers.get(this.near.key)?.trip === 'there') this.onVisit(this.near.id)
      else this.onSelect(this.near)
      e.preventDefault()
    }
  }
  private keyup = (e: KeyboardEvent) => { this.keys.delete(e.key.toLowerCase()) }
  private blur = () => { this.keys.clear() }

  private collides(x: number, y: number) {
    const L = this.L!
    const [W, H] = L.grid
    if (x < 0.5 || y < 0.5 || x > W - 0.5 || y > H - 0.5) return true
    const r = 0.28
    for (const [cx, cy] of [[x - r, y], [x + r, y], [x, y - 0.2]]) if (L.ground[Math.floor(cy) * W + Math.floor(cx)] === Ground.Water) return true
    return L.blocks.some(b => x + r > b.x && x - r < b.x + b.w && y > b.y && y - 0.3 < b.y + b.h)
  }

  private stepPlayer(dt: number) {
    const p = this.player
    if (!p || !this.L) return
    let vx = 0, vy = 0
    const k = this.keys
    if (k.has('a') || k.has('arrowleft')) vx -= 1
    if (k.has('d') || k.has('arrowright')) vx += 1
    if (k.has('w') || k.has('arrowup')) vy -= 1
    if (k.has('s') || k.has('arrowdown')) vy += 1
    if (vx || vy) { p.target = null; this.follow = true; this.cam = null }
    else if (p.target) {
      const dx = p.target[0] - p.x, dy = p.target[1] - p.y, d = Math.hypot(dx, dy)
      if (d < 0.1) p.target = null
      else { vx = dx / d; vy = dy / d }
    }
    const n = Math.hypot(vx, vy)
    p.moving = n > 0
    if (!n) return
    const v = SPEED * (k.has('shift') ? 1.7 : 1) * dt / n
    const nx = p.x + vx * v, ny = p.y + vy * v
    const before = [p.x, p.y]
    if (!this.collides(nx, p.y)) p.x = nx
    if (!this.collides(p.x, ny)) p.y = ny
    if (p.x === before[0] && p.y === before[1]) p.target = null      // walked into a wall: stop trying
    if (vx) p.dir = vx > 0 ? 1 : -1
    p.dist += Math.hypot(p.x - before[0], p.y - before[1])
  }

  private findNear(): Thing | null {
    const p = this.player
    if (!p || !this.L) return null
    let best: Thing | null = null, bd = REACH
    for (const t of this.L.things) {
      let d = Math.hypot(t.door[0] - p.x, t.door[1] - p.y)
      const w = t.npc && this.walkers.get(t.key)
      if (w) d = Math.min(d, Math.hypot(w.x - p.x, w.y - p.y) + 0.3)
      if (d < bd) { bd = d; best = t }
    }
    return best
  }

  // ---------- the ground, painted once, in chunks ----------
  // One canvas for the whole island would be W × H × 16 × res pixels: a mid-sized town on the painted
  // theme is past what phones allow (iOS stops at ~16 Mpx and draws nothing). So it's 32-tile squares,
  // each small, and only the ones on screen are copied each frame.

  private paintGround(L: Layout): Chunk[] {
    const [W, H] = L.grid
    const out: Chunk[] = []
    // each chunk is painted a tile past its edges, so neighbours overlap: at a fractional zoom the copies
    // would otherwise leave hairline seams between them
    for (let y = 0; y < H; y += CHUNK) for (let x = 0; x < W; x += CHUNK) {
      const x0 = Math.max(0, x - 1), y0 = Math.max(0, y - 1)
      const w = Math.min(W, x + CHUNK + 1) - x0, h = Math.min(H, y + CHUNK + 1) - y0
      out.push({ cv: this.paintChunk(L, x0, y0, w, h), x: x0, y: y0, w, h })
    }
    return out
  }

  private paintChunk(L: Layout, x0: number, y0: number, w: number, h: number): HTMLCanvasElement {
    const th = this.theme, R = th.res
    const [W, H] = L.grid
    const cv = document.createElement('canvas')
    cv.width = w * T * R; cv.height = h * T * R
    const c = cv.getContext('2d')!
    c.scale(R, R)
    c.translate(-x0 * T, -y0 * T)              // draw in world pixels; the canvas shows this chunk's window
    const p = new Paint(c, th)
    const g = (x: number, y: number) => (x < 0 || y < 0 || x >= W || y >= H ? Ground.Water : L.ground[y * W + x])
    const x1 = x0 + w, y1 = y0 + h
    const touches = (r: Rect, m: number) => r.x + r.w + m > x0 && r.x - m < x1 && r.y + r.h + m > y0 && r.y - m < y1

    const soft = th.style === 'soft'
    const land = (x: number, y: number) => g(x, y) !== Ground.Water
    if (soft) {                                    // painted style: water everywhere, then rounded shores
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) this.tileWater(p, x * T, y * T, x, y)
      c.fillStyle = css(th.sand)                   // a shore circle reaches a tile over, so look one past the edge
      for (let y = y0 - 1; y <= y1; y++) for (let x = x0 - 1; x <= x1; x++) if (land(x, y)) { c.beginPath(); c.arc(x * T + 8, y * T + 8, 13, 0, 7); c.fill() }
    }
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const px = x * T, py = y * T, k = g(x, y)
      if (soft && (k === Ground.Water || !land(x - 1, y) || !land(x + 1, y) || !land(x, y - 1) || !land(x, y + 1))) continue
      if (k === Ground.Water) this.tileWater(p, px, py, x, y)
      else if (k === Ground.Sand) this.tileFlat(p, px, py, th.sand, x, y, true)
      else if (k === Ground.Plaza) this.tileCobble(p, px, py, x, y)
      else this.tileGrass(p, px, py, x, y, 0.97 + noise(x / 5, y / 5, 11) * 0.08)
      if (!soft && k !== Ground.Water) {                                           // foam where land meets water
        c.fillStyle = 'rgba(255,255,255,0.45)'
        if (g(x, y - 1) === Ground.Water) c.fillRect(px, py, T, 1)
        if (g(x, y + 1) === Ground.Water) c.fillRect(px, py + T - 1, T, 1)
        if (g(x - 1, y) === Ground.Water) c.fillRect(px, py, 1, T)
        if (g(x + 1, y) === Ground.Water) c.fillRect(px + T - 1, py, 1, T)
      }
    }
    // roads: stamped discs along each line, edge first, then the surface. Only the stretches that cross
    // this chunk (a road a tile wide, so a tile of slack)
    const segs = (line: Pt[]): Pt[][] => {
      const out: Pt[][] = []
      for (let i = 1; i < line.length; i++) {
        const [ax, ay] = line[i - 1], [bx, by] = line[i]
        const r = { x: Math.min(ax, bx), y: Math.min(ay, by), w: Math.abs(bx - ax), h: Math.abs(by - ay) }
        if (touches(r, 1.2)) out.push([line[i - 1], line[i]])
      }
      return out
    }
    const stamp = (line: Pt[], r: number, col: [number, number, number], k: number) => {
      if (soft) {                                  // painted: one smooth stroke
        c.strokeStyle = css(col, k); c.lineWidth = r * 2; c.lineCap = 'round'; c.lineJoin = 'round'
        c.beginPath(); line.forEach(([x, y], i) => (i ? c.lineTo(x * T, y * T) : c.moveTo(x * T, y * T))); c.stroke()
        return
      }
      c.fillStyle = css(col, k)                    // pixels: flat discs along the line
      for (let i = 1; i < line.length; i++) {
        const [ax, ay] = line[i - 1], [bx, by] = line[i]
        const n = Math.ceil(Math.hypot(bx - ax, by - ay) * 4)
        for (let j = 0; j <= n; j++) {
          const t = j / n, cx = (ax + (bx - ax) * t) * T, cy = (ay + (by - ay) * t) * T
          for (let dy = -r; dy <= r; dy++) {
            const half = Math.round(Math.sqrt(r * r - dy * dy))
            c.fillRect(Math.round(cx - half), Math.round(cy + dy), half * 2, 1)
          }
        }
      }
    }
    const here = L.roads.map(segs)
    for (const road of here) for (const sg of road) stamp(sg, 14, th.path, 0.8)
    for (const road of here) for (const sg of road) stamp(sg, 12, th.path, 1)
    for (const r of L.roads) for (let i = 0; i < r.length; i += 1) {                // ruts and pebbles
      const [x, y] = r[i]
      if (x < x0 - 1 || x > x1 + 1 || y < y0 - 1 || y > y1 + 1) continue
      const h = hash(i, Math.round(x * 7))
      c.fillStyle = css(th.path, h < 0.5 ? 0.85 : 1.1); c.fillRect(Math.round(x * T + (h - 0.5) * 14), Math.round(y * T + (hash(i, 3) - 0.5) * 14), 2, 1)
    }
    // each block: a wash of its team's colour and a kerb round it, so a team reads as one place
    for (const d of L.districts) {
      if (!touches(d, 1)) continue
      c.fillStyle = css(d.color, 1, 0.1); c.strokeStyle = css(d.color, 0.9, 0.75); c.lineWidth = 2
      c.setLineDash(d.empty ? [6, 5] : [])                                         // a plot with no houses yet
      c.beginPath(); c.roundRect(d.x * T, d.y * T, d.w * T, d.h * T, soft ? 10 : 2); c.fill(); c.stroke()
      c.setLineDash([])
    }
    // the square's paving ring
    if (touches({ x: L.plaza.x - L.plaza.r, y: L.plaza.y - L.plaza.r, w: 2 * L.plaza.r, h: 2 * L.plaza.r }, 1)) {
      c.strokeStyle = css(th.cobble, 0.75); c.lineWidth = 3
      c.beginPath(); c.arc(L.plaza.x * T, L.plaza.y * T, L.plaza.r * T - 2, 0, 7); c.stroke()
    }
    return cv
  }

  private tileGrass(p: Paint, px: number, py: number, x: number, y: number, k = 1) {
    const th = this.theme, c = p.c
    c.fillStyle = css(th.grass[0], k); c.fillRect(px, py, T, T)
    if (th.style === 'soft') {
      for (let i = 0; i < 3; i++) {
        const r = hash(x * 3 + i, y * 7)
        c.fillStyle = css(th.grass[1 + (i % 2)], k, 0.35); c.beginPath(); c.arc(px + r * 16, py + hash(y, x + i) * 16, 4 + r * 4, 0, 7); c.fill()
      }
    } else {
      for (let i = 0; i < 6; i++) {
        const r = hash(x * 11 + i, y * 5 + i)
        c.fillStyle = css(th.grass[r < 0.5 ? 1 : 2], k)
        c.fillRect(px + Math.floor(r * 15), py + Math.floor(hash(y + i, x) * 14), 1, 2)
      }
    }
    const f = hash(x * 7, y * 3)
    if (f < 0.05) { c.fillStyle = css(th.flowers[Math.floor(f * 60) % th.flowers.length]); c.fillRect(px + 6, py + 7, 2, 2); c.fillRect(px + 10, py + 11, 2, 2) }
  }

  private tileFlat(p: Paint, px: number, py: number, col: [number, number, number], x: number, y: number, road: boolean) {
    const c = p.c
    c.fillStyle = css(col, road ? 1 : 0.92); c.fillRect(px, py, T, T)
    for (let i = 0; i < 5; i++) {
      const r = hash(x * 13 + i, y * 17 + i)
      c.fillStyle = css(col, r < 0.5 ? 0.86 : 1.08)
      c.fillRect(px + Math.floor(r * 15), py + Math.floor(hash(y + i, x) * 15), 2, 1)
    }
  }

  private tileCobble(p: Paint, px: number, py: number, x: number, y: number) {
    const c = p.c, col = this.theme.cobble
    c.fillStyle = css(col, 0.8); c.fillRect(px, py, T, T)
    for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) {
      c.fillStyle = css(col, 0.95 + hash(x * 2 + i, y * 2 + j) * 0.15)
      c.fillRect(px + i * 8 + ((y + j) % 2 ? 2 : 0) + 1, py + j * 8 + 1, 6, 6)
    }
  }

  private tileWater(p: Paint, px: number, py: number, x: number, y: number) {
    const c = p.c, col = this.theme.water
    c.fillStyle = css(col); c.fillRect(px, py, T, T)
    c.fillStyle = css(col, 1.25, 0.6)
    const r = hash(x, y)
    c.fillRect(px + 3 + r * 6, py + 5, 5, 1); c.fillRect(px + 8 - r * 4, py + 11, 4, 1)
  }

  // ---------- sprites, cached per theme ----------

  private sprite(key: string, w: number, h: number, draw: (p: Paint) => Anchors | void) {
    let s = this.sprites.get(key)
    if (!s) {
      const R = this.theme.res, cv = document.createElement('canvas')
      cv.width = Math.ceil(w * R); cv.height = Math.ceil(h * R)
      const c = cv.getContext('2d')!
      c.scale(R, R)
      const anchors = draw(new Paint(c, this.theme, w * 31 + h)) || undefined
      s = { cv, anchors }
      this.sprites.set(key, s)
    }
    return s
  }

  private spriteKey(t: Thing): string {
    const s = t.spec
    return s ? `h:${s.style}:${s.color}:${s.tier}:${s.stories}:${s.tools.length}:${s.banner}` : t.kind === 'station' ? `s:${t.color}` : t.kind === 'post' ? `p:${t.color}` : `b:${t.style}:${t.color}`
  }
  private decorKey(d: Decor): string { return `${d.kind}:${Math.floor(d.r * 4)}` }

  private buildingSprite(t: Thing) {
    const w = t.w * T, h = t.h * T, key = this.spriteKey(t)
    if (t.spec) {
      const s = t.spec
      return this.sprite(key, w, h + PAD, p => { p.c.translate(0, PAD); return drawHouse(p, s) })
    }
    if (t.kind === 'station') return this.sprite(key, w, h + PAD, p => { p.c.translate(0, PAD); drawToolStall(p, t.color) })
    if (t.kind === 'post') return this.sprite(key, w, h + PAD, p => { p.c.translate(0, PAD); drawPostOffice(p, t.color) })
    return this.sprite(key, w, h + PAD, p => { p.c.translate(0, PAD); drawBuilding(p, t.style, t.color) })
  }

  // ---------- NPCs ----------

  private yard(t: Thing): Rect { return { x: t.door[0] - 2.2, y: t.door[1] + 0.1, w: 4.4, h: 1.5 } }

  private walker(t: Thing): Walker {
    let w = this.walkers.get(t.key)
    const y = this.yard(t)
    if (!w || (!w.trip && (w.x < y.x - 1 || w.x > y.x + y.w + 1 || w.y > y.y + y.h + 1))) {
      const r = hash(t.id, t.key.length)
      w = { x: y.x + r * y.w, y: y.y + y.h * 0.5, tx: 0, ty: 0, wait: r * 2, dir: 1, dist: 0 }
      w.tx = w.x; w.ty = w.y
      this.walkers.set(t.key, w)
    }
    return w
  }

  private stepWalker(t: Thing, w: Walker, dt: number, s: RunStatus | null | undefined) {
    if (w.trip === 'there') return false                       // waiting for you in the square
    if (w.trip) {                                              // along the street, a point at a time
      const p = w.path?.[0]
      if (!p) { w.trip = w.trip === 'going' ? 'there' : undefined; w.path = undefined; w.dir = 1; return false }
      const dx = p[0] - w.x, dy = p[1] - w.y, d = Math.hypot(dx, dy)
      w.tx = p[0]; w.ty = p[1]
      if (d < 0.08) { w.path!.shift(); return true }
      const v = Math.min(d, 2.4 * dt)
      w.x += dx / d * v; w.y += dy / d * v; w.dist += v
      if (Math.abs(dx) > 0.02) w.dir = dx > 0 ? 1 : -1
      return true
    }
    const atWork = s === 'busy' || s === 'starting'
    if (atWork) { w.tx = t.door[0] + 0.7; w.ty = t.door[1] - 0.2; w.wait = 0 }
    const dx = w.tx - w.x, dy = w.ty - w.y, d = Math.hypot(dx, dy)
    if (d > 0.05) {
      const v = Math.min(d, (atWork ? 2.6 : 1.1) * dt)
      w.x += dx / d * v; w.y += dy / d * v; w.dist += v
      if (Math.abs(dx) > 0.02) w.dir = dx > 0 ? 1 : -1
      return true
    }
    if (atWork) return false
    w.wait -= dt
    if (w.wait <= 0) {
      const y = this.yard(t)
      w.tx = y.x + Math.random() * y.w; w.ty = y.y + Math.random() * y.h; w.wait = 1 + Math.random() * 3
    }
    return false
  }

  // ---------- each frame ----------

  private focus(): Set<string> | null {
    if (!this.selected || !this.L) return null
    const s = new Set([this.selected])
    for (const w of this.L.wires) {
      if (w.from.key === this.selected) s.add(w.to.key)
      if (w.to.key === this.selected) s.add(w.from.key)
    }
    return s
  }

  /** When something is selected: arcs from its tools to it (or from a tool to the agents that use it). */
  private drawTrails(c: CanvasRenderingContext2D, now: number) {
    if (!this.selected) return
    for (const w of this.L!.wires) {
      if (w.from.key !== this.selected && w.to.key !== this.selected) continue
      const a: Pt = [w.from.door[0] * T, w.from.door[1] * T], b: Pt = [w.to.door[0] * T, w.to.door[1] * T]
      const mid: Pt = [(a[0] + b[0]) / 2, Math.min(a[1], b[1]) - 40]
      c.strokeStyle = w.team ? 'rgba(190,140,255,0.95)' : css(STATUS_COLOR[w.status], 1, 0.9); c.lineWidth = 2
      c.setLineDash(w.status === 'connected' ? [5, 4] : [2, 4]); c.lineDashOffset = -now / 50
      c.beginPath(); c.moveTo(a[0], a[1]); c.quadraticCurveTo(mid[0], mid[1], b[0], b[1]); c.stroke()
    }
    c.setLineDash([]); c.lineWidth = 1
  }

  /** A name tag. A lead's has a gold rim, so you can tell who runs each colony. */
  private label(text: string, sx: number, sy: number, size = 11, sub?: string, dim = false, sel = false, lead = false) {
    const c = this.ctx, th = this.theme
    c.font = th.font(size)
    const w1 = c.measureText(text).width
    c.font = th.font(size - 2, false)
    const w2 = sub ? c.measureText(sub).width : 0
    const w = Math.max(w1, w2) + 12, h = sub ? size * 2 + 7 : size + 8
    c.globalAlpha = dim ? 0.55 : 1
    c.fillStyle = sel ? '#ffd98f' : th.label.bg
    c.beginPath(); c.roundRect(Math.round(sx - w / 2), Math.round(sy - h), Math.round(w), h, th.style === 'pixel' ? 0 : 5); c.fill()
    if (lead) { c.strokeStyle = '#e0a526'; c.lineWidth = 2.5; c.stroke() }
    else if (th.label.edge !== 'transparent') { c.strokeStyle = th.label.edge; c.lineWidth = 1; c.stroke() }
    c.textAlign = 'center'; c.fillStyle = sel ? '#241f2e' : th.label.fg
    c.font = th.font(size); c.fillText(text, sx, sy - (sub ? size + 2 : 5))
    if (sub) { c.font = th.font(size - 2, false); c.fillStyle = sel ? '#5a4a30' : th.label.sub; c.fillText(sub, sx, sy - 5) }
    c.globalAlpha = 1
  }

  private frame = (now: number) => {
    // always ask for the next frame first: one bad frame mustn't freeze the map
    this.raf = requestAnimationFrame(this.frame)
    if (this.paused) return
    try { this.draw(now) } catch (e) { console.error(e) }
  }

  private draw(rawNow: number) {
    const c = this.ctx, th = this.theme
    const dt = Math.min(0.1, (rawNow - (this.last || rawNow)) / 1000)
    this.last = rawNow
    const now = reduceMotion() ? 0 : rawNow        // less motion: things still move, but nothing flickers or sparkles
    const dpr = window.devicePixelRatio || 1
    c.setTransform(1, 0, 0, 1, 0, 0)
    c.fillStyle = th.bg; c.fillRect(0, 0, this.canvas.width, this.canvas.height)
    if (!this.L || !this.ground.length) return

    this.stepPlayer(dt)
    this.stepCompanion(dt)
    this.stepCouriers(dt, now)
    this.near = this.findNear()
    const pl = this.player!
    if (this.follow) {                                   // keep you in the middle of the open space
      const [cx, cy] = this.center()
      if (this.view.zoom < 2) this.view.zoom = 2
      this.cam = [cx - pl.x * T * this.view.zoom, cy - (pl.y - 0.6) * T * this.view.zoom]
    }

    if (this.cam) this.cam = this.bounded(this.cam[0], this.cam[1], this.view.zoom)
    ;[this.view.x, this.view.y] = this.bounded(this.view.x, this.view.y, this.view.zoom)

    const z = this.view.zoom
    c.setTransform(z * dpr, 0, 0, z * dpr, this.view.x * dpr, this.view.y * dpr)
    c.imageSmoothingEnabled = th.style === 'soft'
    // what's on screen, in tiles, with room for tall sprites: nothing outside it is drawn or sorted
    const vx0 = -this.view.x / z / T - 3, vy0 = -this.view.y / z / T - 4, vx1 = (innerWidth - this.view.x) / z / T + 3, vy1 = (innerHeight - this.view.y) / z / T + 3
    const onScreen = (x: number, y: number, w = 0, h = 0) => x + w > vx0 && x < vx1 && y + h > vy0 && y < vy1
    for (const ch of this.ground) if (onScreen(ch.x, ch.y, ch.w, ch.h)) c.drawImage(ch.cv, ch.x * T, ch.y * T, ch.w * T, ch.h * T)
    const focus = this.focus()

    // everything that stands up, painted back to front
    const items = this.items
    items.length = 0
    for (const d of this.L.decor) {
      if (!onScreen(d.x, d.y)) continue
      const [w, h] = DECOR_SIZE[d.kind], dx = d.x * T - w / 2, dy = d.y * T - h
      if (d.kind === 'fountain') { items.push({ y: d.y * T, draw: () => { c.save(); c.translate(dx, dy); drawFountain(new Paint(c, th), now); c.restore() } }); continue }
      const s = this.sprite(this.decorKey(d), w, h, p => {
        switch (d.kind) {
          case 'tree': return drawTree(p, d.r)
          case 'bush': return drawBush(p, d.r)
          case 'rock': return drawRock(p, d.r)
          case 'flowers': return drawFlowers(p, d.r)
          case 'lamp': return drawLamp(p)
          case 'bench': return drawBench(p)
          case 'stall': return drawStall(p, d.r)
          case 'hay': return drawHay(p)
          case 'sign': return drawSignpost(p)
        }
      })
      items.push({ y: d.y * T, draw: () => c.drawImage(s.cv, dx, dy, w, h) })
    }
    const carry = this.carry
    for (const t of this.L.things) {
      const dim = !!focus && !focus.has(t.key)
      const held = carry?.t === t
      const st = t.kind === 'agent' ? this.status.get(t.id) : null
      if (t.npc && !held) this.stepWalker(t, this.walker(t), dt, st)      // off screen, it still wanders (and is where you left it)
      if (!held && !onScreen(t.x, t.y, t.w, t.h + 2)) continue
      const bx = (held ? carry.x : t.x) * T, by = (held ? carry.y : t.y) * T, bw = t.w * T, bh = t.h * T
      items.push({ y: by + bh, draw: () => {
        const s = this.buildingSprite(t)
        c.globalAlpha = dim ? 0.55 : 1
        c.drawImage(s.cv, bx, by - PAD, bw, bh + PAD)
        c.save(); c.translate(bx, by)
        const paint = new Paint(c, th)
        const awake = st === 'ready' || st === 'busy' || st === 'starting'
        if (t.kind === 'post') { const n = this.posts.get(t.id); if (n) drawPostLive(paint, n.waiting, n.threads, now) }
        else if (t.spec && s.anchors) drawHouseLive(paint, t.spec, s.anchors, now, st === 'busy')
        else if (t.kind !== 'station') drawLive(paint, t.style, t.color, now, false)
        // apps' icons, drawn live so they stay sharp at any zoom: on a stall's board, and on the plates
        // of every house that may use that app, so the two match up
        c.textAlign = 'center'; c.textBaseline = 'middle'
        if (t.icon) { c.font = EMOJI_FONT(12); c.fillText(t.icon, STALL_SIGN.x + STALL_SIGN.w / 2, STALL_SIGN.y + STALL_SIGN.h / 2 - 0.5) }
        if (t.spec) { c.font = EMOJI_FONT(8); annexSlots(t.spec).forEach(([x, y], i) => c.fillText(t.spec!.tools[i].icon, x + 5.5, y + 5.5)) }
        c.textBaseline = 'alphabetic'
        if (t.kind === 'agent') {
          // a lantern by the door: dark while it sleeps, flickering as it wakes, lit while it's up
          const lx = (t.door[0] - t.x) * T + 9, ly = bh - 18
          c.fillStyle = css(th.dark); c.fillRect(lx, ly, 2, 14); c.fillRect(lx - 1, ly - 4, 4, 4)
          if (awake) {
            const k = st === 'starting' ? (Math.sin(now / 60) > 0 ? 1 : 0.35) : 0.85 + 0.15 * Math.sin(now / 300)
            c.fillStyle = `rgba(255,214,110,${0.3 * k})`; c.beginPath(); c.arc(lx + 1, ly - 2, 7, 0, 7); c.fill()
            c.fillStyle = `rgba(255,226,140,${k})`; c.fillRect(lx, ly - 3, 2, 2)
          } else if (!awake) {                                  // asleep: z z z drifting off the roof
            for (let i = 0; i < 3; i++) {
              const ph = (now / 2400 + i / 3 + t.id * 0.37) % 1
              c.globalAlpha = (dim ? 0.3 : 0.75) * Math.sin(ph * Math.PI)
              c.fillStyle = '#f4ead2'; c.font = `700 ${7 + i}px ${th.style === 'soft' ? 'Georgia' : 'monospace'}`
              c.fillText('z', bw * 0.7 + ph * 10 + i * 3, -6 - ph * 16 - i * 4)
            }
            c.globalAlpha = dim ? 0.55 : 1
          }
        }
        if (t.kind === 'station' && t.status) {                      // the tool's status lamp
          const col = STATUS_COLOR[t.status], pulse = t.status === 'connected' ? 0.6 + 0.4 * Math.sin(now / 400) : 1
          c.fillStyle = css(col, 1, 0.35 * pulse); c.beginPath(); c.arc(bw - 3, bh - 26, 4, 0, 7); c.fill()
          c.fillStyle = css(col); c.fillRect(bw - 5, bh - 28, 3, 3)
        }
        if (this.selected === t.key) {
          c.strokeStyle = `rgba(255,217,143,${0.7 + 0.3 * Math.sin(now / 250)})`; c.lineWidth = 2
          c.strokeRect(-3, -PAD / 2, bw + 6, bh + PAD / 2 + 3)
        }
        if (held) {                                                   // where it would go: green if it fits there
          c.fillStyle = carry.ok ? 'rgba(90,220,120,0.25)' : 'rgba(235,80,70,0.3)'
          c.strokeStyle = carry.ok ? 'rgba(90,220,120,0.95)' : 'rgba(235,80,70,0.95)'; c.lineWidth = 2
          c.setLineDash([4, 3]); c.fillRect(-T / 2, 0, bw + T, bh + 2.2 * T); c.strokeRect(-T / 2, 0, bw + T, bh + 2.2 * T); c.setLineDash([])
        } else if (this.editing) {
          c.strokeStyle = 'rgba(255,255,255,0.55)'; c.lineWidth = 1; c.setLineDash([3, 3])
          c.strokeRect(-2, -PAD / 4, bw + 4, bh + PAD / 4 + 2); c.setLineDash([])
        }
        c.restore(); c.globalAlpha = 1
      } })
      if (t.npc && !held) {
        const w = this.walker(t)
        const walking = Math.hypot(w.tx - w.x, w.ty - w.y) > 0.05
        const pose: NpcPose = { dir: w.dir, step: Math.floor(w.dist * 6), walking, bob: walking ? 0 : (Math.sin(now / 500 + t.id) > 0.6 ? 1 : 0) }
        items.push({ y: w.y * T, draw: () => {
          c.globalAlpha = dim ? 0.55 : 1
          this.drawPerson(c, w.x, w.y, { color: t.npc!.color, seed: t.npc!.seed, role: t.npc!.role, brain: t.npc!.brain }, { ...pose, now })
          const s = t.npc!.brain?.scale ?? 1
          c.save(); c.translate(Math.round(w.x * T), Math.round(w.y * T)); c.scale(s, s)
          const visit = this.visits.get(t.id)
          if (visit && w.trip === 'there') drawVisitBubble(new Paint(c, th), visit.kind, now)
          else if (st === 'busy' || st === 'starting' || st === 'error' || st === 'ready') drawBubble(new Paint(c, th), st, now)
          if (this.selected === t.key) {
            const b = Math.round(Math.sin(now / 200) * 2)
            c.fillStyle = '#ffd98f'; c.beginPath(); c.moveTo(-4, -36 + b); c.lineTo(4, -36 + b); c.lineTo(0, -31 + b); c.fill()
          }
          c.restore(); c.globalAlpha = 1
        } })
      }
    }
    for (const cr of this.couriers) {
      const [x, y] = this.courierAt(cr)
      if (!onScreen(x / T, y / T)) continue
      items.push({ y, draw: () => {
        c.save(); c.translate(Math.round(x), Math.round(y)); if (cr.dir < 0) c.scale(-1, 1)
        const p = new Paint(c, th)
        if (cr.vehicle === 'boat') drawBoat(p, cr.color, now)
        else if (cr.vehicle === 'cart') drawCart(p, cr.color, Math.floor(cr.dist / 5))
        else drawHorse(p, cr.color, Math.floor(cr.dist / 4))
        c.restore()
        if (cr.live) {                                         // on an errand right now: a sparkle trail
          c.fillStyle = `rgba(255,240,170,${0.5 + 0.5 * Math.sin(now / 90)})`
          c.fillRect(Math.round(x - cr.dir * 12), Math.round(y - 14), 2, 2)
        }
      } })
    }
    items.push({ y: pl.y * T, draw: () => this.drawPerson(c, pl.x, pl.y, { color: [230, 190, 70], seed: 3, role: 'player' },
      { dir: pl.dir, step: Math.floor(pl.dist * 5), walking: pl.moving, bob: 0 }) })
    const mc = this.companion
    if (mc) {
      const w = mc.w, walking = Math.hypot(w.tx - w.x, w.ty - w.y) > 0.25
      items.push({ y: w.y * T, draw: () => {
        this.drawPerson(c, w.x, w.y, mc.look, { dir: w.dir, step: Math.floor(w.dist * 6), walking, bob: walking ? 0 : (Math.sin(now / 500) > 0.6 ? 1 : 0), now })
        const v = this.visits.get(mc.id)
        if (v) { c.save(); c.translate(Math.round(w.x * T), Math.round(w.y * T)); c.scale(mc.look.brain?.scale ?? 1, mc.look.brain?.scale ?? 1)
          drawVisitBubble(new Paint(c, th), v.kind, now); c.restore() }
      } })
    }
    if (pl.target) {
      const r = 3 + Math.sin(now / 150)
      c.strokeStyle = 'rgba(255,255,255,0.8)'; c.lineWidth = 1
      c.beginPath(); c.ellipse(pl.target[0] * T, pl.target[1] * T, r * 1.6, r * 0.8, 0, 0, 7); c.stroke()
    }
    items.sort((a, b) => a.y - b.y).forEach(i => i.draw())
    this.drawTrails(c, now)

    // names and prompts, in screen space so they stay readable at any zoom
    c.setTransform(dpr, 0, 0, dpr, 0, 0)
    if (th.style === 'soft') {                           // painted light: warm centre, dark edges
      const g = c.createRadialGradient(innerWidth / 2, innerHeight * 0.45, innerHeight * 0.2, innerWidth / 2, innerHeight / 2, innerWidth * 0.75)
      g.addColorStop(0, 'rgba(255,214,150,0.10)'); g.addColorStop(1, 'rgba(10,8,24,0.55)')
      c.fillStyle = g; c.fillRect(0, 0, innerWidth, innerHeight)
    }
    const screen = (wx: number, wy: number): Pt => [this.view.x + wx * z, this.view.y + wy * z]
    for (const d of this.L.decor) if (d.kind === 'sign' && d.text && onScreen(d.x, d.y)) {
      const [sx, sy] = screen(d.x * T, d.y * T - 17)
      this.label(d.text, sx, sy, z < 1.2 ? 12 : 13)
    }
    for (const t of this.L.things) {
      if (carry?.t !== t && !onScreen(t.x, t.y, t.w, t.h + 2)) continue
      const sel = this.selected === t.key, dim = !!focus && !focus.has(t.key)
      // zoomed out, only the block names and the leads are named; closer in, everyone and every stall
      const visiting = this.visits.has(t.id) && t.kind === 'agent' && this.walkers.get(t.key)?.trip === 'there'
      const stall = t.kind === 'station' || t.kind === 'post'
      const shown = sel || visiting || this.near === t || (focus?.has(t.key) ?? false) || (stall ? z > 1.6 || (this.posts.get(t.id)?.waiting ?? 0) > 0 && t.kind === 'post'
        : z > 1.1 || t.lead || t.kind !== 'agent')
      if (!shown && carry?.t !== t) continue
      if (carry?.t === t) {
        const [sx, sy] = screen((carry.x + t.w / 2) * T, carry.y * T - PAD / 2 + 4)
        this.label(t.label, sx, sy, 11, carry.why ?? 'drop it here', false, true)
      } else if (t.npc) {                                                   // the name rides on the character
        const w = this.walkers.get(t.key)
        const b = t.npc.brain
        // a visitor's name and errand go over its speech box
        if (w) { const [sx, sy] = screen(w.x * T, w.y * T - (visiting ? 46 : 22) * (b?.scale ?? 1) - (b?.gear === 'crown' || b?.gear === 'feather' ? 3 : 0))
          const said = visiting ? this.visits.get(t.id)!.text : ''
          this.label(t.label, sx, sy - (visiting ? (this.visitOrder.indexOf(t.id) % 2) * 26 : 0), z < 1.2 ? 9 : 10,
            visiting ? (said.length > 34 ? said.slice(0, 33) + '…' : said) : (sel || z > 1.6) && b?.words ? b.words : undefined, dim, sel || visiting, t.lead) }
      } else if (stall) {                                                 // under the counter: its board shows the icon
        const [sx, sy] = screen((t.x + t.w / 2) * T, (t.y + t.h) * T)
        this.label(t.label, sx, sy + (z > 1.3 || sel ? 30 : 20), 9, z > 1.3 || sel ? t.sub : undefined, dim, sel)
      } else {
        const [sx, sy] = screen((t.x + t.w / 2) * T, t.y * T - PAD / 2 + 4)
        this.label(t.label, sx, sy, z < 1.2 ? 9 : 11, z > 1.3 ? t.sub : undefined, dim, sel, t.lead)
      }
    }
    const [px, py] = screen(pl.x * T, pl.y * T - 24)
    if (this.near && !this.editing) {
      const came = this.near.kind === 'agent' && this.visits.has(this.near.id) && this.walkers.get(this.near.key)?.trip === 'there'
      const verb = this.near.kind === 'station' ? 'Visit' : this.near.kind === 'agent' || this.near.kind === 'shared' ? 'Talk to' : 'Open'
      this.label(came ? `E · Hear ${this.near.label} out` : `E · ${verb} ${this.near.label}`, px, py - 2, 12, undefined, false, true)
    } else this.label(this.playerName, px, py, z < 1.2 ? 9 : 10)
    if (mc) {                                                          // the mayor: its name, and how to talk to it
      const v = this.visits.get(mc.id), b = mc.look.brain
      const [sx, sy] = screen(mc.w.x * T, mc.w.y * T - (v ? 46 : 22) * (b?.scale ?? 1) - (b?.gear === 'crown' || b?.gear === 'feather' ? 3 : 0))
      const said = v ? (v.text.length > 34 ? v.text.slice(0, 33) + '…' : v.text) : z > 1.3 ? 'M · talk' : undefined
      this.label(mc.name, sx, sy, z < 1.2 ? 9 : 10, said, false, !!v)
    }

    if (this.cam) {
      this.view.x += (this.cam[0] - this.view.x) * 0.12
      this.view.y += (this.cam[1] - this.view.y) * 0.12
      if (!this.follow && Math.abs(this.cam[0] - this.view.x) + Math.abs(this.cam[1] - this.view.y) < 0.5) this.cam = null
    }
  }

  private drawPerson(c: CanvasRenderingContext2D, x: number, y: number, look: Parameters<typeof drawNpc>[1], pose: NpcPose) {
    const th = this.theme
    c.save(); c.translate(Math.round(x * T), Math.round(y * T))
    const s = look.brain?.scale ?? 1
    c.scale(s, s)
    if (pose.dir < 0 && th.style !== 'soft') c.scale(-1, 1)
    drawNpc(new Paint(c, th, look.seed), look, { ...pose, dir: th.style !== 'soft' ? 1 : pose.dir })
    c.restore()
  }

  // ---------- picking & input ----------

  private toWorld(cx: number, cy: number): Pt { return [(cx - this.view.x) / this.view.zoom, (cy - this.view.y) / this.view.zoom] }

  pick(cx: number, cy: number): Thing | null {
    if (!this.L) return null
    const [px, py] = this.toWorld(cx, cy)
    for (const t of this.editing ? [] : this.L.things) {               // NPCs first: they stand in front
      const w = t.npc && this.walkers.get(t.key)
      if (w && Math.abs(px - w.x * T) < 8 * (t.npc!.brain?.scale ?? 1) && py < w.y * T + 2 && py > w.y * T - 22 * (t.npc!.brain?.scale ?? 1)) return t
    }
    const order = [...this.L.things].sort((a, b) => (b.y + b.h) - (a.y + a.h))
    for (const t of order) {
      if (px >= t.x * T && px <= (t.x + t.w) * T && py >= t.y * T - PAD / 2 && py <= (t.y + t.h) * T) return t
    }
    return null
  }

  private down = (e: PointerEvent) => {
    this.cam = null; this.follow = false
    this.pointers.set(e.pointerId, [e.clientX, e.clientY])
    if (this.pointers.size === 2) {                   // a second finger: a pinch, not a drag or a tap
      const [a, b] = [...this.pointers.values()]
      this.pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, zoom: this.view.zoom, mid: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] }
      this.drag = null; this.carry = null
      return
    }
    const hit = this.editing && this.pick(e.clientX, e.clientY)
    if (hit && hit.kind !== 'station' && hit.kind !== 'post') {   // pick the building up (stalls and post offices stay in their courtyard)
      const [wx, wy] = this.toWorld(e.clientX, e.clientY), t = hit
      this.carry = { t, dx: wx / T - t.x, dy: wy / T - t.y, x: t.x, y: t.y, ok: true, id: e.pointerId }
      this.canvas.setPointerCapture?.(e.pointerId)
      return
    }
    this.drag = { x: e.clientX, y: e.clientY, vx: this.view.x, vy: this.view.y, moved: false, id: e.pointerId }
  }

  private move = (e: PointerEvent) => {
    if (this.pointers.has(e.pointerId)) this.pointers.set(e.pointerId, [e.clientX, e.clientY])
    if (this.pinch && this.pointers.size >= 2) {
      const [a, b] = [...this.pointers.values()]
      const z = Math.max(this.minZoom(), Math.min(MAX_ZOOM, this.pinch.zoom * (Math.hypot(a[0] - b[0], a[1] - b[1]) || 1) / this.pinch.d))
      const [mx, my] = this.pinch.mid
      this.view.x = mx - (mx - this.view.x) * z / this.view.zoom
      this.view.y = my - (my - this.view.y) * z / this.view.zoom
      this.view.zoom = z
      return
    }
    const cr = this.carry
    if (cr && e.pointerId === cr.id && this.L) {
      const [wx, wy] = this.toWorld(e.clientX, e.clientY)
      cr.x = Math.round((wx / T - cr.dx) * 2) / 2; cr.y = Math.round((wy / T - cr.dy) * 2) / 2   // half-tile steps
      cr.why = cr.x === cr.t.x && cr.y === cr.t.y ? undefined : whyNot(this.L, cr.t, cr.x, cr.y) ?? undefined
      cr.ok = !cr.why
      this.canvas.style.cursor = cr.ok ? 'grabbing' : 'not-allowed'
      return
    }
    if (this.drag && e.pointerId === this.drag.id) {
      const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y
      if (Math.abs(dx) + Math.abs(dy) > 4) this.drag.moved = true
      if (this.drag.moved) { this.view.x = this.drag.vx + dx; this.view.y = this.drag.vy + dy }
      return
    }
    if (e.target !== this.canvas) return
    this.canvas.style.cursor = this.pick(e.clientX, e.clientY) ? (this.editing ? 'grab' : 'pointer') : 'grab'
  }

  private up = (e: PointerEvent) => {
    this.pointers.delete(e.pointerId)
    if (this.pinch) { if (this.pointers.size < 2) this.pinch = null; this.drag = null; return }
    const cr = this.carry
    if (cr && e.pointerId === cr.id) {                               // put it down, if it fits; otherwise it goes back
      this.carry = null
      if (cr.ok && (cr.x !== cr.t.x || cr.y !== cr.t.y)) this.onMove(cr.t, cr.x, cr.y)
      return
    }
    if (this.drag && !this.drag.moved && e.target === this.canvas && this.player && !this.editing) {
      const who = this.visitorAt(e.clientX, e.clientY)
      if (who) { this.drag = null; this.onVisit(who.id); return }
      if (this.companionAt(e.clientX, e.clientY)) { this.drag = null; this.onCompanion(); return }
      const hit = this.pick(e.clientX, e.clientY)
      if (hit) { this.player.target = [hit.door[0], hit.door[1] + 0.2]; this.onSelect(hit) }
      else { const [wx, wy] = this.toWorld(e.clientX, e.clientY); this.player.target = [wx / T, wy / T]; this.onSelect(null) }
    }
    this.drag = null
  }

  private companionAt(cx: number, cy: number): boolean {
    const w = this.companion?.w
    if (!w) return false
    const [wx, wy] = this.toWorld(cx, cy)
    return Math.abs(wx / T - w.x) < 0.7 && wy / T > w.y - 2.4 && wy / T < w.y + 0.4
  }

  /** A lead waiting for you in the square, under the pointer: its body or its speech box. */
  private visitorAt(cx: number, cy: number): Thing | null {
    const [wx, wy] = this.toWorld(cx, cy)
    const x = wx / T, y = wy / T
    return this.L?.things.find(t => {
      const w = t.kind === 'agent' && this.visits.has(t.id) ? this.walkers.get(t.key) : undefined
      return !!w && w.trip === 'there' && Math.abs(x - w.x) < 0.8 && y > w.y - 3 && y < w.y + 0.4
    }) ?? null
  }

  private wheel = (e: WheelEvent) => {
    e.preventDefault()
    this.cam = null; this.follow = false
    const z = Math.max(this.minZoom(), Math.min(MAX_ZOOM, this.view.zoom * Math.exp(-e.deltaY * 0.0015)))
    this.view.x = e.clientX - (e.clientX - this.view.x) * z / this.view.zoom
    this.view.y = e.clientY - (e.clientY - this.view.y) * z / this.view.zoom
    this.view.zoom = z
  }
}
