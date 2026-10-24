// Where everything stands on the map, in tiles. Plain data in, plain data out; render.ts draws it.
//
// The town is a grid of city blocks round a square with a fountain. Each team is one block: the lead
// first, its team beside it, all around a courtyard where the team's tools stand as market stalls (one
// for each app anyone on the team may use). Agents without a team share a block; people's shared
// agents have one too. Streets run between the blocks; it's all on an island with ponds and woods.
// Everything is seeded by your username, so your town looks the same every visit.
//
// Each block (and the square) is an area, like a div: it has its own corner, and a building you moved
// (city.town) is saved from that corner, so it moves with its colony when the town re-flows. It can go
// anywhere in its area's room (its cell of the grid, inside the streets), and the block's box grows to
// wrap it. The caretaker is shown the same areas (App.tsx snapshot, backend/app/caretaker.py).
//
// A colony's lead always stands nearest the square, set apart from its team in front of it, in the
// biggest house of its colony with a flag on the roof. Moves that would put a member nearer are refused.
//
// Every colony has a post office in a corner of its own, on the block's far side from the square: where its
// mail comes and goes (backend/app/mail.py). Like the stalls, it stays where its block puts it.
// The mayor has no house: it walks beside you (render.ts), and apps only it uses aren't drawn.

import type { City, Connection, MyAgent, RunStatus, Status } from '../api'
import { agentCount, coloniesOf, colonyName, isMayor, leads } from '../colony'
import { brainLook, type BrainLook } from './brain'
import { agentBuilding, houseSize, houseSpec, toolBuilding, toolLook, type BuildingStyle, type HouseSpec } from './kinds'

export type RGB = [number, number, number]
export type Pt = [number, number]
export type ThingKind = 'agent' | 'shared' | 'library' | 'station' | 'files' | 'post'
export type Rect = { x: number; y: number; w: number; h: number }
export type Npc = { seed: number; color: RGB; role: BuildingStyle; status: RunStatus | null; brain?: BrainLook }
export type Thing = Rect & {                // x, y, w, h: the sprite's area in tiles; it stands on y + h
  key: string; kind: ThingKind; id: number
  style: BuildingStyle; color: RGB; spec?: HouseSpec
  door: Pt                                  // where you stand to talk to it
  via?: { road: number; at: number }        // where its footpath meets a road (roads[road][at])
  label: string; sub?: string; status?: Status; npc?: Npc
  server?: string                           // a tool's name in agents' tool calls: mcp__<server>__…
  lead?: boolean                            // leads a team: still named when the map is zoomed out
  icon?: string                             // a tool's icon, on its stall's sign
  area: string                              // the area it belongs to: a block's key, or 'square'
}
/** A block on the map: one team (or the agents with no team, or people's shared agents). */
export type District = Rect & { key: string; name: string; color: RGB; empty?: boolean }   // empty: a colony with no agents yet
/** A block or the square. corner: what its buildings' saved spots count from; room: where they may stand. */
export type Area = { key: string; corner: Pt; room: Rect }
export type Decor = { kind: 'tree' | 'bush' | 'rock' | 'lamp' | 'bench' | 'stall' | 'hay' | 'flowers' | 'fountain' | 'sign'; x: number; y: number; r: number; text?: string }
export type Wire = { from: Thing; to: Thing; status: Status; team?: boolean }
export const Ground = { Water: 0, Sand: 1, Grass: 2, Plaza: 4 } as const
export type Ground = typeof Ground[keyof typeof Ground]
export type Layout = {
  grid: [number, number]; ground: Uint8Array        // one Ground per tile, row by row
  things: Thing[]; wires: Wire[]; roads: Pt[][]; decor: Decor[]
  plaza: { x: number; y: number; r: number }
  districts: District[]; courts: Rect[]             // the blocks, and their paved courtyards and lanes
  blocks: Rect[]                                    // what you can't walk through (besides water)
  spawn: Pt; home: Rect                             // where you start; what "Fit" frames on a phone
  origin: Pt                                        // where the square's middle sits in the world
  areas: Record<string, Area>                       // every block by its key, and 'square'
}

export const T = 16                                 // art pixels per tile
const STALL = 2                                     // a tool's market stall, in tiles

export const hex = (c: string): RGB => {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c)
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [138, 111, 209]
}

export const STATUS_COLOR: Record<Status, RGB> = {
  connected: [60, 207, 110], auth_required: [242, 181, 58], error: [229, 83, 75],
  needs_sandbox: [90, 160, 230], unknown: [154, 160, 166],
}

export const STATUS_LABEL: Record<Status, string> = {
  connected: 'connected', auth_required: 'needs credentials', error: 'error',
  needs_sandbox: 'runs in sandbox', unknown: 'not checked',
}

export const seedOf = (s: string) => [...s].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7)

function rng(seed: number) {                         // mulberry32: small, fast, repeatable
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const h2 = (x: number, y: number, s: number) => {
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(s | 0, 982451653)) | 0
  h = Math.imul(h ^ (h >>> 13), 1274126177)
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}
/** Smooth value noise in [0, 1]. */
export function noise(x: number, y: number, s: number) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf)
  const a = h2(xi, yi, s), b = h2(xi + 1, yi, s), c = h2(xi, yi + 1, s), d = h2(xi + 1, yi + 1, s)
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v
}

type Item = Omit<Thing, 'x' | 'y' | 'door' | 'area'>
/** A building plus its front yard: what nothing else may stand on. */
const yardOf = (t: Rect): Rect => ({ x: t.x - 0.5, y: t.y, w: t.w + 1, h: t.h + 2.2 })
const doorOf = (it: Pick<Thing, 'spec'>, r: Rect): Pt => [r.x + (it.spec ? houseSize(it.spec).body / T : STALL) / 2, r.y + r.h + 0.6]
const overlaps = (a: Rect, b: Rect, m = 0) => a.x - m < b.x + b.w && a.x + a.w + m > b.x && a.y - m < b.y + b.h && a.y + a.h + m > b.y
const within = (a: Rect, room: Rect) => a.x >= room.x && a.y >= room.y && a.x + a.w <= room.x + room.w && a.y + a.h <= room.y + room.h

function distToPolyline(p: Pt, line: Pt[]) {
  let best = Infinity
  for (let i = 1; i < line.length; i++) {
    const [ax, ay] = line[i - 1], [bx, by] = line[i]
    const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy || 1
    const t = Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    best = Math.min(best, Math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy))
  }
  return best
}

/** Whether a building may stand with its top-left corner at (x, y): inside its area's room, clear of
 *  other buildings and their yards, of every road, and of the square. */
function clear(t: Thing, x: number, y: number, things: Thing[], roads: Pt[][], plaza: { x: number; y: number; r: number }, room?: Rect) {
  const ft = yardOf({ x, y, w: t.w, h: t.h })
  if (room && !within(ft, room)) return false
  if (things.some(o => o !== t && overlaps(ft, yardOf(o), 0.3))) return false
  const nx = Math.max(ft.x, Math.min(plaza.x, ft.x + ft.w)), ny = Math.max(ft.y, Math.min(plaza.y, ft.y + ft.h))
  if (Math.hypot(nx - plaza.x, ny - plaza.y) < plaza.r + 1) return false
  const pts: Pt[] = [[ft.x, ft.y], [ft.x + ft.w, ft.y], [ft.x, ft.y + ft.h], [ft.x + ft.w, ft.y + ft.h], [ft.x + ft.w / 2, ft.y + ft.h / 2],
    [ft.x + ft.w / 2, ft.y], [ft.x + ft.w / 2, ft.y + ft.h], [ft.x, ft.y + ft.h / 2], [ft.x + ft.w, ft.y + ft.h / 2]]
  return roads.every(r => pts.every(p => distToPolyline(p, r) > 1.1))
}

/** How far a building's middle is from the square's. */
const reach = (r: Rect, sq: Pt) => Math.hypot(r.x + r.w / 2 - sq[0], r.y + r.h / 2 - sq[1])

/** Whether its colony's lead would still stand nearest the square with t at (x, y). */
function leadFirst(t: Thing, x: number, y: number, things: Thing[], sq: Pt) {
  const mine = things.filter(o => o.area === t.area && o.kind === 'agent')
  const lead = mine.find(o => o.lead)
  if (!lead || t.kind !== 'agent') return true
  const here = reach({ x, y, w: t.w, h: t.h }, sq)
  return t === lead ? mine.every(o => o === t || reach(o, sq) > here) : here > reach(lead, sq)
}

/** Why this building can't be dropped here (world tiles, as drawn), or null if it can. */
export function whyNot(L: Layout, t: Thing, x: number, y: number): string | null {
  const [W, H] = L.grid
  if (!(x > 1 && y > 1 && x + t.w < W - 1 && y + t.h + 2.2 < H - 1) || !clear(t, x, y, L.things, L.roads, L.plaza, L.areas[t.area]?.room))
    return "can't go here"
  if (!leadFirst(t, x, y, L.things, [L.plaza.x, L.plaza.y])) return 'the lead stays nearest the square'
  return null
}

export const canPlace = (L: Layout, t: Thing, x: number, y: number) => whyNot(L, t, x, y) === null

/** Stand a building at (x, y), joined to the nearest road for couriers (no footpath is drawn: blocks have none). */
function settle(t: Thing, x: number, y: number, roads: Pt[][]) {
  t.x = x; t.y = y
  t.door = doorOf(t, t)
  t.via = undefined
  let best = { road: -1, at: 0, d: Infinity }
  roads.forEach((r, i) => r.forEach((p, j) => {
    const d = Math.hypot(p[0] - t.door[0], p[1] - t.door[1])
    if (d < best.d) best = { road: i, at: j, d }
  }))
  if (best.road < 0) return
  t.via = { road: best.road, at: best.at }
}

/** The nearest clear spot in its room to where a building stands now, spiralling out. */
function freeSpot(t: Thing, things: Thing[], roads: Pt[][], plaza: { x: number; y: number; r: number }, room?: Rect): Pt | null {
  for (let r = 1; r < 40; r += 0.75) for (let k = 0; k < 16; k++) {
    const a = k * Math.PI / 8, x = t.x + Math.cos(a) * r, y = t.y + Math.sin(a) * r
    if (clear(t, x, y, things, roads, plaza, room)) return [x, y]
  }
  return null
}

/** The way a courier travels from one building to another: down its footpath, along its road to the
 *  square, across, and out along the other road. Points in tiles. */
export function route(L: Layout, from: Thing, to: Thing): Pt[] {
  if (!from.via || !to.via) return [from.door, to.door]
  const a = L.roads[from.via.road], b = L.roads[to.via.road]
  if (from.via.road === to.via.road) {
    const [i, j] = [from.via.at, to.via.at]
    const mid = i <= j ? a.slice(i, j + 1) : a.slice(j, i + 1).reverse()
    return [from.door, ...mid, to.door]
  }
  return [from.door, ...a.slice(0, from.via.at + 1).reverse(), [L.plaza.x, L.plaza.y + L.plaza.r * 0.55],
    ...b.slice(0, to.via.at + 1), to.door]
}

/** The way a lead walks from its house to a spot in the square: down its footpath, along its street to
 *  the point nearest the square, then across. Points in tiles. */
export function toSquare(L: Layout, from: Thing, spot: Pt): Pt[] {
  if (!from.via) return [from.door, spot]
  const road = L.roads[from.via.road]
  const near = road.reduce((bi, p, i) => Math.hypot(p[0] - L.plaza.x, p[1] - L.plaza.y) < Math.hypot(road[bi][0] - L.plaza.x, road[bi][1] - L.plaza.y) ? i : bi, 0)
  const i = from.via.at
  return [from.door, ...(i <= near ? road.slice(i, near + 1) : road.slice(near, i + 1).reverse()), spot]
}

/** Where the leads who've come to see you stand: in a row between the fountain and where you start,
 *  facing you. A long queue wraps into a second row. */
export function meetingSpot(L: Layout, i: number, n: number): Pt {
  const per = 5, row = Math.floor(i / per), inRow = Math.min(per, n - row * per)
  return [L.plaza.x + (i % per - (inRow - 1) / 2) * 1.6, L.plaza.y + 2.3 - row * 1.4]
}

/** A lane round the island, out at sea, for boats. */
export function seaLane(L: Layout): Pt[] {
  const [W, H] = L.grid, m = 1.1
  return [[m, m], [W - m, m], [W - m, H - m], [m, H - m], [m, m]]
}

const GAP = 1.2                                     // between houses in a row
const STREET = 3.2                                  // between blocks
const COURT = 5.4                                   // under a block's first row: door yards, then its stalls
const LANE = 2.8                                    // under its other rows
const EDGE = 1                                      // a block's margin
const PER_ROW = 6
const LEAD_GAP = 2.6                                // between a lead's house and its team: set apart
const SPARE = 6                                     // spare ground in each block's cell, away from the square: room to move houses

type Block = { key: string; name: string; color: RGB; items: Item[]; tools: Item[]; lead?: Item; empty?: boolean; post?: Item }
type Spot = { it: Item; x: number; y: number }
type Shape = { w: number; h: number; spots: Spot[]; courts: Rect[]; sign: Pt; front?: Rect }   // front: the lead's yard

/** Houses in rows (doors to the south), a paved courtyard under the first row with the stalls, a lane
 *  under each other row. Positions are from the block's top-left corner; the top is left for its name. */
function rowsOf(items: Item[], tools: Item[]): Shape {
  const n = items.length
  const per = Math.ceil(n / Math.max(1, Math.ceil(n / PER_ROW)))
  const rows: Item[][] = []
  for (let i = 0; i < n; i += per) rows.push(items.slice(i, i + per))
  const rowW = rows.map(r => r.reduce((s, it) => s + it.w, 0) + GAP * (r.length - 1))
  const w = Math.max(...rowW, tools.length * (STALL + 0.9), 8) + EDGE * 2
  const spots: Spot[] = [], courts: Rect[] = []
  let top = 2.6
  rows.forEach((r, k) => {
    const base = top + Math.max(...r.map(it => it.h))
    let x = (w - rowW[k]) / 2
    for (const it of r) { spots.push({ it, x, y: base - it.h }); x += it.w + GAP }
    const band = k === 0 ? COURT : LANE
    courts.push({ x: 0.4, y: base + 0.3, w: w - 0.8, h: band - 0.5 })
    if (k === 0) {
      const x0 = (w - tools.length * (STALL + 0.9) + 0.9) / 2
      tools.forEach((t, i) => spots.push({ it: t, x: x0 + i * (STALL + 0.9), y: base + 2.4 }))
    }
    top = base + band + 0.4
  })
  return { w, h: top - 0.4, spots, courts, sign: [w / 2, 1.9] }
}

/** A block, with its lead's house at its head: on the side facing the square (`toward`: -1, 0 or 1 on
 *  each axis), so every lead stands near you and its team sits behind it. */
function arrange(b: Block, toward: Pt): Shape {
  if (b.empty) return { w: 12, h: 8, spots: [], courts: [], sign: [6, 1.9] }   // a plot waiting for its agents
  if (!b.lead || !b.items.length) return rowsOf(b.lead ? [b.lead, ...b.items] : b.items, b.tools)
  const team = rowsOf(b.items, b.tools), L = b.lead
  const lh = L.h + 2.6                                       // the lead's house and its front yard
  const [hx, hy] = toward
  let w: number, h: number, lx: number, ly: number, ix = 0, iy = 0, sign = team.sign
  if (hx) {                                                  // beside its team, on the square's side
    w = team.w + L.w + LEAD_GAP; h = Math.max(team.h, lh + 3)
    if (hx > 0) lx = team.w + LEAD_GAP - 1.2; else { lx = 1.2; ix = L.w + LEAD_GAP }
    ly = hy > 0 ? h - lh : hy < 0 ? 2.6 : Math.max(2.6, (h - lh) / 2)
    sign = [ix + team.w / 2, 1.9]
  } else {                                                   // above or below its team
    w = Math.max(team.w, L.w + 2 * EDGE); h = team.h + lh + LEAD_GAP - 1
    lx = (w - L.w) / 2; ix = (w - team.w) / 2
    if (hy > 0) ly = team.h + LEAD_GAP - 1.2; else { ly = 2.6; iy = lh + LEAD_GAP - 1; sign = [Math.max(3, lx / 2), 1.9] }
  }
  return {
    w, h, sign,
    spots: [{ it: L, x: lx, y: ly }, ...team.spots.map(sp => ({ ...sp, x: sp.x + ix, y: sp.y + iy }))],
    front: { x: lx - 0.8, y: ly + L.h + 0.3, w: L.w + 1.6, h: 2.1 },
    courts: team.courts.map(c => ({ ...c, x: c.x + ix, y: c.y + iy })),
  }
}

/** The block with its post office in a column of its own, on the side away from the square (`toward`), at the
 *  far corner, so it never sits among the houses or the stalls. */
function withPost(s: Shape, post: Item | undefined, toward: Pt): Shape {
  if (!post) return s
  const col = STALL + 1.4, left = toward[0] > 0, shift = left ? col : 0
  const x = left ? 0.6 : s.w + 0.8
  const y = toward[1] > 0 ? 2.6 : Math.max(2.6, s.h - STALL - 0.6)
  return {
    w: s.w + col, h: Math.max(s.h, y + STALL + 0.6), sign: [s.sign[0] + shift, s.sign[1]],
    spots: [...s.spots.map(sp => ({ ...sp, x: sp.x + shift })), { it: post, x, y }],
    courts: [...s.courts.map(c => ({ ...c, x: c.x + shift })), { x: x - 0.4, y: y + STALL + 0.1, w: STALL + 0.8, h: 0.9 }],
    front: s.front && { ...s.front, x: s.front.x + shift },
  }
}

/** Everything the layout depends on, as one string: the same key means the same map, so a reload that
 *  changed nothing the map shows (a diary edit, a routine) doesn't redraw or re-place anything. */
function layoutKey(city: City): string {
  const me = city.me
  const agents = me ? city.agents.map(a => [a.id, a.slug, a.name, a.color, a.lines, a.files.length, a.share_id, a.team, a.building, a.colony_name, a.role ?? '',
    a.run_status ?? null, a.brain ? [a.brain.provider, a.brain.model, a.brain.thinking] : null, a.description.length]) : []
  const conns = me ? city.connections.map(c => [c.id, c.name, c.app, c.url, c.command, c.status, c.granted_to.map(g => g.agent_id)]) : []
  const pub = city.public.map(s => [s.id, s.kind, s.owner, s.title, s.agent ? [s.agent.slug, s.agent.name, s.agent.color, s.agent.lines, s.agent.files.length, s.agent.building] : null])
  return JSON.stringify([me?.username ?? null, agents, conns, pub, me ? city.shared_files.length : 0, me ? city.town : null])
}
let last: { key: string; L: Layout } | null = null

export function layout(city: City): Layout {
  const key = layoutKey(city)
  if (last?.key === key) return last.L
  const L = build(city)
  last = { key, L }
  return L
}

function build(city: City): Layout {
  const rand = rng(seedOf(city.me?.username ?? 'agent-town'))
  const things: Thing[] = [], roads: Pt[][] = [], decor: Decor[] = [], courts: Rect[] = [], districts: District[] = []
  const plaza = { x: 0, y: 0, r: 4.5 }
  const fronts = new Map<string, Rect>()                          // a lead's front yard, which moves with its house
  const mine = city.me ? city.agents : []
  const conns = city.me ? city.connections : []

  // who lives with whom: each colony (a lead and its team) is a block
  const { colonies, loners, leadOf } = coloniesOf(mine)
  const toolsOf = (agentId: number) => conns.filter(c => c.granted_to.some(g => g.agent_id === agentId)).map(toolLook)
  // a lead's house is bigger than any on its team (as far as sizes go), with a flag in the colony's colour
  const item = (a: MyAgent, crew: Item[] = []): Item => {
    const style = agentBuilding(a), color = hex(a.color)
    let spec = houseSpec({ lines: a.lines, files: a.files.length, tools: toolsOf(a.id), shared: !!a.share_id }, style, color)
    if (leads(a)) {
      const top = (k: 'tier' | 'stories') => Math.max(spec[k], ...crew.map(m => m.spec ? m.spec[k] + 1 : 0))
      spec = { ...spec, tier: Math.min(3, Math.max(1, top('tier'))) as HouseSpec['tier'], stories: Math.min(3, top('stories')) as HouseSpec['stories'], banner: true }
    }
    const s = houseSize(spec)
    const team = a.team?.length ? `leads ${a.team.length}` : leadOf.has(a.id) ? `${leadOf.get(a.id)!.name}'s team` : ''
    return { key: `agent:${a.id}`, kind: 'agent' as const, id: a.id, style, color, spec, w: s.w / T, h: s.h / T, label: a.name,
      sub: [team, a.share_id ? 'shared' : ''].filter(Boolean).join(' · ') || undefined, lead: leads(a),
      npc: { seed: seedOf(a.slug), color, role: style, status: a.run_status ?? null, brain: brainLook(a.brain) } }
  }

  // the blocks: one per team, then the agents with no team (eight to a block), then the public's
  const blocks: (Block & { agents: number[] })[] = []
  for (const { lead, members } of colonies) {
    const team = [lead, ...members], items = members.map(m => item(m))
    const post: Item = { key: `post:${lead.id}`, kind: 'post', id: lead.id, style: 'post', color: hex(lead.color), w: STALL, h: STALL,
      label: 'Post office', sub: colonyName(lead) }
    blocks.push({ key: `colony:${lead.id}`, name: `${colonyName(lead)} · ${agentCount(team.length)}`, color: hex(lead.color),
      lead: item(lead, items), items, tools: [], post, agents: team.map(a => a.id) })
  }
  ;(city.me ? city.empty_colonies ?? [] : []).forEach((e, i) =>   // colonies named before any agents are in them
    blocks.push({ key: `colony:empty-${i + 1}`, name: `${e.name} · no agents yet`, color: [150, 140, 125], items: [], tools: [], agents: [], empty: true }))
  for (let i = 0; i < loners.length; i += 8) {
    const some = loners.slice(i, i + 8)
    blocks.push({ key: i ? `colony:agents-${i / 8 + 1}` : 'colony:agents', name: blocks.some(b => !b.empty) ? 'More agents' : 'Your agents',
      color: [150, 140, 125], items: some.map(a => item(a)), tools: [], agents: some.map(a => a.id) })
  }
  // each block's courtyard has a stall for every app anyone in it may use; apps nobody uses yet stand in the square
  const stallsOf = new Map<string, number[]>()                    // a stall's key -> the agents beside it who may use it
  const used = new Set<number>()
  const stall = (c: Connection, agents: number[]): Item => {
    const key = used.has(c.id) ? `station:${c.id}@${stallsOf.size}` : `station:${c.id}`
    used.add(c.id); stallsOf.set(key, agents)
    const look = toolLook(c)
    return { key, kind: 'station' as const, id: c.id, style: toolBuilding(c), color: look.color, icon: look.icon, w: STALL, h: STALL,
      label: c.name, sub: STATUS_LABEL[c.status], status: c.status,
      server: c.app || c.name.toLowerCase().replace(/[^a-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '') }
  }
  for (const b of blocks) for (const c of conns) {
    const who = b.agents.filter(id => c.granted_to.some(g => g.agent_id === id))
    if (who.length) b.tools.push(stall(c, who))
  }
  const mayor = new Set(mine.filter(isMayor).map(a => a.id))     // apps only the mayor uses (Agent Town's own) aren't drawn
  const loose = conns.filter(c => !used.has(c.id) && !(c.granted_to.length && c.granted_to.every(g => mayor.has(g.agent_id))))
    .map(c => stall(c, []))

  const pub: Item[] = []
  const sharedFiles = city.public.filter(s => s.kind === 'file' && s.file)
  if (sharedFiles.length) pub.push({ key: 'library', kind: 'library', id: 0, style: 'library', color: [150, 104, 70], w: 4, h: 4,
    label: 'Library', sub: `${sharedFiles.length} shared files` })
  for (const sh of city.public.filter(s => s.kind === 'agent' && s.agent)) {
    const a = sh.agent!, style = agentBuilding(a), color = hex(a.color)
    const spec = houseSpec({ lines: a.lines, files: a.files.length, tools: [], shared: true }, style, color)
    const s = houseSize(spec)
    pub.push({ key: `shared:${sh.id}`, kind: 'shared', id: sh.id, style, color, spec, w: s.w / T, h: s.h / T, label: a.name, sub: `@${sh.owner}`,
      npc: { seed: seedOf(`${sh.owner}/${a.slug}`), color, role: style, status: null } })
  }
  if (pub.length) blocks.push({ key: 'colony:neighbours', name: city.me ? 'Neighbours' : 'Agent Town', color: [150, 104, 70], items: pub, tools: [], agents: [] })

  // the square, in the middle cell: fountain, your shared files, and any apps no agent uses yet
  const files = city.me ? city.shared_files ?? [] : []
  const vault: Item | null = files.length ? { key: 'files', kind: 'files', id: 0, style: 'vault', color: [92, 112, 140], w: 4, h: 4,
    label: 'Shared files', sub: `${files.length} files, all your agents` } : null
  const square = { w: Math.max(2 * plaza.r + 3 + (vault ? 6 : 0), 2 + loose.length * (STALL + 0.9)), h: 2 * plaza.r + 3 + (loose.length ? 3.6 : 0) }

  // blocks on a grid round the square: the first ones (your first teams) right next to it
  // each block's lead faces the square, and the block is pushed against it in its cell
  const cols = Math.max(1, Math.ceil(Math.sqrt(blocks.length + 1))), nrows = Math.ceil((blocks.length + 1) / cols)
  const mid = Math.floor((nrows - 1) / 2) * cols + Math.floor((cols - 1) / 2)
  const far = (i: number) => Math.hypot(i % cols - mid % cols, Math.floor(i / cols) - Math.floor(mid / cols))
  const slots = [...Array(nrows * cols).keys()].filter(i => i !== mid).sort((a, b) => far(a) - far(b) || a - b)
  const toward = (cell: number): Pt => [Math.sign(mid % cols - cell % cols), Math.sign(Math.floor(mid / cols) - Math.floor(cell / cols))]
  const shapes = blocks.map((b, k) => withPost(arrange(b, toward(slots[k])), b.post, toward(slots[k])))
  const size = (cell: number): [number, number] => {
    if (cell === mid) return [square.w, square.h]
    const k = slots.indexOf(cell)
    return k >= 0 && k < shapes.length ? [shapes[k].w + SPARE, shapes[k].h + SPARE] : [0, 0]
  }
  const colW = [...Array(cols).keys()].map(c => Math.max(...[...Array(nrows).keys()].map(r => size(r * cols + c)[0])))
  const rowH = [...Array(nrows).keys()].map(r => Math.max(...[...Array(cols).keys()].map(c => size(r * cols + c)[1])))
  const cellX = colW.map((_, c) => STREET + colW.slice(0, c).reduce((s, w) => s + w + STREET, 0))
  const cellY = rowH.map((_, r) => STREET + rowH.slice(0, r).reduce((s, h) => s + h + STREET, 0))
  const totalW = cellX[cols - 1] + colW[cols - 1] + STREET, totalH = cellY[nrows - 1] + rowH[nrows - 1] + STREET

  // the square's middle is (0, 0): saved spots (city.town) are relative to it
  const mc = mid % cols, mr = Math.floor(mid / cols)
  const sqX = cellX[mc] + (colW[mc] - square.w) / 2, sqY = cellY[mr] + (rowH[mr] - square.h) / 2
  const ox = sqX + plaza.r + 1.5, oy = sqY + plaza.r + 1.5
  const put = (it: Item, x: number, y: number, area: string) => {
    const rect = { x: x - ox, y: y - oy, w: it.w, h: it.h }
    things.push({ ...it, ...rect, area, door: doorOf(it, rect) })
  }
  const cellRect = (c: number, r: number): Rect => ({ x: cellX[c] - ox, y: cellY[r] - oy, w: colW[c], h: rowH[r] })
  const areas: Record<string, Area> = { square: { key: 'square', corner: [0, 0], room: cellRect(mc, mr) } }
  const signs = new Map<string, Decor>()
  if (vault) put(vault, sqX + 2 * plaza.r + 4, sqY + plaza.r - 1, 'square')
  loose.forEach((t, i) => put(t, sqX + 1 + i * (STALL + 0.9), sqY + 2 * plaza.r + 3.4, 'square'))
  shapes.forEach((s, k) => {
    const cell = slots[k], c = cell % cols, r = Math.floor(cell / cols), b = blocks[k]
    const [hx, hy] = toward(cell)
    const bx = cellX[c] + (colW[c] - s.w) * (hx > 0 ? 1 : hx < 0 ? 0 : 0.5), by = cellY[r] + (rowH[r] - s.h) * (hy > 0 ? 1 : hy < 0 ? 0 : 0.5)
    areas[b.key] = { key: b.key, corner: [bx - ox, by - oy], room: cellRect(c, r) }
    for (const sp of s.spots) put(sp.it, bx + sp.x, by + sp.y, b.key)
    for (const ct of s.courts) courts.push({ ...ct, x: bx + ct.x - ox, y: by + ct.y - oy })
    if (s.front) { const f = { ...s.front, x: bx + s.front.x - ox, y: by + s.front.y - oy }; courts.push(f); fronts.set(b.lead!.key, f) }
    districts.push({ key: b.key, x: bx - ox, y: by - oy, w: s.w, h: s.h, name: b.name, color: b.color, empty: b.empty })
    const sign: Decor = { kind: 'sign', x: bx + s.sign[0] - ox, y: by + s.sign[1] - oy, r: 0, text: b.name }
    decor.push(sign); signs.set(b.key, sign)
  })
  // streets between all the blocks, a point every tile
  const street = (a: Pt, b: Pt) => {
    const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1])))
    roads.push([...Array(n + 1).keys()].map(i => [a[0] + (b[0] - a[0]) * i / n - ox, a[1] + (b[1] - a[1]) * i / n - oy] as Pt))
  }
  for (let c = 0; c <= cols; c++) { const x = c < cols ? cellX[c] - STREET / 2 : totalW - STREET / 2; street([x, STREET / 2], [x, totalH - STREET / 2]) }
  for (let r = 0; r <= nrows; r++) { const y = r < nrows ? cellY[r] - STREET / 2 : totalH - STREET / 2; street([STREET / 2, y], [totalW - STREET / 2, y]) }

  // the houses you moved stand where you put them, counted from their area's corner; anything they now
  // sit on steps aside (stalls stay put). A spot outside its room (it changed colony, the town grew) is dropped.
  const town = city.me ? city.town ?? {} : {}
  const spotOf = (t: Thing): Pt | null => {
    const p = town[t.key], a = areas[t.area]
    if (!p || !a || t.kind === 'station' || t.kind === 'post') return null
    const x = a.corner[0] + p[0], y = a.corner[1] + p[1]
    return within(yardOf({ x, y, w: t.w, h: t.h }), a.room) ? [x, y] : null
  }
  const moved = new Map(things.map(t => [t, spotOf(t)] as const).filter((e): e is [Thing, Pt] => !!e[1]))
  const auto = new Map(things.map(t => [t, [t.x, t.y] as Pt]))      // where the blocks put them
  const shifted = new Set<string>()                                // areas whose houses aren't where the block put them
  const move = (t: Thing, x: number, y: number) => {
    settle(t, x, y, roads)
    shifted.add(t.area)
    const f = fronts.get(t.key)
    if (f) { f.x = t.x - 0.8; f.y = t.y + t.h + 0.3 }
  }
  for (const [t, [x, y]] of moved) move(t, x, y)
  // the lead stays nearest the square: a saved spot that breaks that (the team changed) is dropped
  for (const lead of things.filter(t => t.lead && t.kind === 'agent')) {
    const team = things.filter(t => t.area === lead.area && t !== lead && t.kind === 'agent')
    const back = (t: Thing) => { moved.delete(t); move(t, ...auto.get(t)!) }
    if (moved.has(lead) && !team.every(m => reach(m, [0, 0]) > reach(lead, [0, 0]))) back(lead)
    for (const m of team) if (moved.has(m) && reach(m, [0, 0]) <= reach(lead, [0, 0])) back(m)
  }
  for (const t of things) {
    if (moved.has(t) || t.kind === 'station' || t.kind === 'post' || ![...moved.keys()].some(m => overlaps(yardOf(t), yardOf(m), 0.3))) continue
    const spot = freeSpot(t, things, roads, plaza, areas[t.area]?.room)
    if (spot) move(t, spot[0], spot[1])
  }
  // a lamp each side of a lead's forecourt
  for (const f of fronts.values()) for (const x of [f.x + 0.2, f.x + f.w - 0.2]) decor.push({ kind: 'lamp', x, y: f.y + f.h - 0.3, r: 0 })
  // the box follows its houses: it grows to wrap any that moved, with room for its name above them
  for (const d of districts) {
    if (!shifted.has(d.key)) continue
    const room = areas[d.key].room
    let x0 = d.x, y0 = d.y, x1 = d.x + d.w, y1 = d.y + d.h
    for (const t of things.filter(t => t.area === d.key)) {
      const y = yardOf(t)
      x0 = Math.min(x0, y.x - 0.3); x1 = Math.max(x1, y.x + y.w + 0.3)
      y0 = Math.min(y0, t.y - 2.6); y1 = Math.max(y1, y.y + y.h)
    }
    x0 = Math.max(x0, room.x); y0 = Math.max(y0, room.y); x1 = Math.min(x1, room.x + room.w); y1 = Math.min(y1, room.y + room.h)
    const sign = signs.get(d.key)
    if (sign && (y0 < d.y || x0 !== d.x || x1 !== d.x + d.w)) { sign.x = (x0 + x1) / 2; sign.y = y0 + 1.9 }
    Object.assign(d, { x: x0, y: y0, w: x1 - x0, h: y1 - y0 })
  }

  // ---- the land: an island around everything, with ponds and woods ----
  const pts = [...things.flatMap(t => [[t.x, t.y], [t.x + t.w, t.y + t.h + 2]] as Pt[]), ...roads.flat(), [-plaza.r, -plaza.r], [plaza.r, plaza.r]] as Pt[]
  const sea = 7
  const minX = Math.min(...pts.map(p => p[0])) - sea, minY = Math.min(...pts.map(p => p[1])) - sea
  const maxX = Math.max(...pts.map(p => p[0])) + sea, maxY = Math.max(...pts.map(p => p[1])) + sea
  const W = Math.ceil(maxX - minX), H = Math.ceil(maxY - minY)
  const sx = -minX, sy = -minY
  const shift = (p: Pt): Pt => [p[0] + sx, p[1] + sy]
  for (const t of things) { t.x += sx; t.y += sy; t.door = shift(t.door) }
  for (const r of [...courts, ...districts]) { r.x += sx; r.y += sy }
  for (const a of Object.values(areas)) { a.corner = shift(a.corner); a.room = { ...a.room, x: a.room.x + sx, y: a.room.y + sy } }
  roads.forEach((r, i) => { roads[i] = r.map(shift) })
  for (const d of decor) { d.x += sx; d.y += sy }
  plaza.x += sx; plaza.y += sy

  const seed = seedOf(city.me?.username ?? 'x') % 1000
  const inside = (x: number, y: number, r: Rect, m: number) => x > r.x - m && x < r.x + r.w + m && y > r.y - m && y < r.y + r.h + m
  // what's built on: one byte per tile, so "is anything within m tiles?" is a look at a few cells, not
  // a walk over every building and every road point for every tile of the island
  const taken = new Uint8Array(W * H)
  const mark = (r: Rect) => {
    for (let y = Math.max(0, Math.floor(r.y)); y < Math.min(H, Math.ceil(r.y + r.h)); y++)
      for (let x = Math.max(0, Math.floor(r.x)); x < Math.min(W, Math.ceil(r.x + r.w)); x++) taken[y * W + x] = 1
  }
  for (const t of things) mark({ ...t, h: t.h + 2 })
  for (const d of districts) mark(d)
  for (const r of roads) for (const [x, y] of r) mark({ x: x - 0.6, y: y - 0.6, w: 1.2, h: 1.2 })
  mark({ x: plaza.x - plaza.r, y: plaza.y - plaza.r, w: 2 * plaza.r, h: 2 * plaza.r })
  const near = (x: number, y: number, m: number) => {
    const k = Math.ceil(m), cx = Math.floor(x), cy = Math.floor(y)
    for (let yy = Math.max(0, cy - k); yy <= Math.min(H - 1, cy + k); yy++)
      for (let xx = Math.max(0, cx - k); xx <= Math.min(W - 1, cx + k); xx++) if (taken[yy * W + xx]) return true
    return false
  }
  const ground = new Uint8Array(W * H)
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const cx = x + 0.5, cy = y + 0.5
    const ex = Math.min(cx, W - cx), ey = Math.min(cy, H - cy)      // distance to the map's edge
    const coast = Math.min(ex, ey) - 1.5 - noise(cx / 4, cy / 4, seed) * 4.5
    let g: Ground = coast < 0 ? Ground.Water : coast < 1 ? Ground.Sand : Ground.Grass
    if (g !== Ground.Grass && near(cx, cy, 1.5)) g = Ground.Grass
    if (Math.hypot(cx - plaza.x, cy - plaza.y) < plaza.r || courts.some(r => inside(cx, cy, r, 0))) g = Ground.Plaza
    ground[y * W + x] = g
  }

  // ponds where there's room
  for (let n = 0; n < 2 + Math.floor((W * H) / 900); n++) {
    const px = 3 + rand() * (W - 6), py = 3 + rand() * (H - 6), r = 1.6 + rand() * 2.2
    if (near(px, py, r + 2)) continue
    for (let y = Math.floor(py - r - 2); y <= py + r + 2; y++) for (let x = Math.floor(px - r - 2); x <= px + r + 2; x++) {
      if (x < 0 || y < 0 || x >= W || y >= H) continue
      const d = Math.hypot(x + 0.5 - px, (y + 0.5 - py) * 1.3) - noise(x / 2, y / 2, seed + 7) * 1.4
      if (d < r) ground[y * W + x] = Ground.Water
      else if (d < r + 0.9 && ground[y * W + x] === Ground.Grass) ground[y * W + x] = Ground.Sand
    }
  }

  // the square: a fountain, benches and a couple of stalls
  decor.push({ kind: 'fountain', x: plaza.x, y: plaza.y + 0.8, r: 0 })
  for (let k = 0; k < 4; k++) {
    const a = k * Math.PI / 2 + Math.PI / 4
    decor.push({ kind: k % 2 ? 'stall' : 'bench', x: plaza.x + Math.cos(a) * (plaza.r - 1.2), y: plaza.y + Math.sin(a) * (plaza.r - 1.2) + 0.5, r: rand() })
  }
  decor.push({ kind: 'sign', x: plaza.x, y: plaza.y - plaza.r - 0.6, r: 0, text: city.me ? `@${city.me.username}'s town` : 'Agent Town' })

  // lamps along the streets, then woods, bushes, rocks and flowers wherever there's grass left
  for (const r of roads) for (let i = 4; i < r.length; i += 6) {
    const [ax, ay] = r[i - 1], [bx, by] = r[i]
    const L = Math.hypot(bx - ax, by - ay) || 1, side = i % 12 < 6 ? 1 : -1
    const lx = bx - (by - ay) / L * 1.4 * side, ly = by + (bx - ax) / L * 1.4 * side
    if (!things.some(t => inside(lx, ly, { ...t, h: t.h + 1 }, 0.3))) decor.push({ kind: 'lamp', x: lx, y: ly, r: 0 })
  }
  for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
    if (ground[y * W + x] !== Ground.Grass) continue
    const cx = x + 0.5, cy = y + 0.5
    if (near(cx, cy, 0.9)) continue
    const woods = noise(x / 6, y / 6, seed + 3), r = h2(x, y, seed)
    if (woods > 0.55 && r < (woods - 0.4) * 1.4) decor.push({ kind: 'tree', x: cx + (r - 0.5) * 0.6, y: cy + 0.5, r: h2(y, x, seed) })
    else if (r < 0.025) decor.push({ kind: 'bush', x: cx, y: cy + 0.4, r: h2(y, x, 1) })
    else if (r < 0.035) decor.push({ kind: 'rock', x: cx, y: cy + 0.3, r: h2(y, x, 2) })
    else if (r < 0.06) decor.push({ kind: 'flowers', x: cx, y: cy, r: h2(y, x, 3) })
  }

  const wires: Wire[] = []
  const byKey = new Map(things.map(t => [t.key, t]))
  for (const [key, ids] of stallsOf) {                             // each stall to the agents beside it who may use it
    const from = byKey.get(key), status = from?.status ?? 'unknown'
    for (const id of ids) {
      const to = byKey.get(`agent:${id}`)
      if (from && to) wires.push({ from, to, status })
    }
  }
  for (const a of mine) {                                          // a lead to each agent on its team
    const from = byKey.get(`agent:${a.id}`)
    for (const id of a.team ?? []) {
      const to = byKey.get(`agent:${id}`)
      if (from && to) wires.push({ from, to, status: 'connected', team: true })
    }
  }
  const blocked: Rect[] = things.map(t => ({ x: t.x + 0.2, y: t.y + t.h * 0.45, w: t.w - 0.4, h: t.h * 0.55 - 0.1 }))
  blocked.push({ x: plaza.x - 1.5, y: plaza.y - 0.7, w: 3, h: 1.9 })              // the fountain
  return {
    grid: [W, H], ground, things, wires, roads, decor, plaza, districts, courts, blocks: blocked,
    spawn: [plaza.x, plaza.y + plaza.r - 1], home: { x: plaza.x - 14, y: plaza.y - 11, w: 28, h: 22 }, origin: [sx, sy], areas,
  }
}

