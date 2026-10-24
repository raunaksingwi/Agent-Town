// What an agent thinks with, turned into how its character looks. The model sets its size and
// its colours (a bigger model is a bigger character), the price sets the metal of its trim, the
// context window the satchel it carries, and thinking effort the aura around it: the harder it
// thinks, the brighter the aura and the more sparks rise off it.

import type { Brain, Thinking } from '../api'
import type { RGB } from './layout'

export type Gear = 'feather' | 'cap' | 'circlet' | 'crown' | 'goggles'
export type BrainLook = {
  scale: number          // 0.85 small and quick … 1.3 the biggest model
  aura: RGB              // the model family's colour
  glow: number           // 0 none … 5 thinking as hard as it can
  trim: RGB | null       // bronze, silver or gold, from the price; null for the cheapest
  satchel: 0 | 1 | 2     // the context window: none, 200K, 1M
  gear: Gear
  words: string          // "Opus 5.5 · Deep", for its name tag
}

// The Claude families, smallest to biggest. Price is $ per million input tokens.
type Family = { match: RegExp; name: string; scale: number; aura: RGB; gear: Gear }
const FAMILIES: Family[] = [
  { match: /haiku/, name: 'Haiku', scale: 0.85, aura: [120, 200, 255], gear: 'feather' },
  { match: /sonnet/, name: 'Sonnet', scale: 1, aura: [110, 220, 160], gear: 'cap' },
  { match: /opus/, name: 'Opus', scale: 1.15, aura: [175, 130, 255], gear: 'circlet' },
  { match: /fable|mythos/, name: 'Fable', scale: 1.3, aura: [255, 205, 90], gear: 'crown' },
]
// What we know about specific models; anything else falls back to its family.
const MODELS: Record<string, { price: number; context: number }> = {
  'claude-haiku-5-5': { price: 0.1, context: 1_000_000 },
  'claude-haiku-4-5': { price: 1, context: 200_000 },
  'claude-sonnet-5-5': { price: 2, context: 1_000_000 },
  'claude-sonnet-5': { price: 2, context: 1_000_000 },
  'claude-sonnet-4-6': { price: 3, context: 1_000_000 },
  'claude-opus-5-5': { price: 4, context: 1_000_000 },
  'claude-opus-5': { price: 5, context: 1_000_000 },
  'claude-opus-4-8': { price: 5, context: 1_000_000 },
  'claude-fable-5-1': { price: 10, context: 1_000_000 },
  'claude-fable-5': { price: 10, context: 1_000_000 },
}
const BRONZE: RGB = [196, 128, 70], SILVER: RGB = [205, 212, 222], GOLD: RGB = [245, 200, 70]
const EFFORT: Record<Thinking, { glow: number; name: string }> = {
  '': { glow: 2, name: '' }, low: { glow: 1, name: 'Quick' }, medium: { glow: 2, name: 'Balanced' },
  high: { glow: 3, name: 'Careful' }, xhigh: { glow: 4, name: 'Deep' }, max: { glow: 5, name: 'Deepest' },
}
const PLAIN: BrainLook = { scale: 1, aura: [200, 200, 200], glow: 0, trim: null, satchel: 0, gear: 'cap', words: '' }

export function brainLook(b: Brain | null | undefined): BrainLook {
  if (!b) return PLAIN                                             // no AI account yet: an ordinary villager
  const effort = EFFORT[b.thinking] ?? EFFORT['']
  const m = b.model.toLowerCase()
  if (b.provider === 'openai') {                                   // Codex: a tinkerer in goggles
    const scale = /mini|nano/.test(m) ? 0.85 : /pro|max/.test(m) ? 1.15 : 1
    return { scale, aura: [80, 200, 190], glow: effort.glow, trim: scale > 1 ? SILVER : null, satchel: 1, gear: 'goggles',
      words: [b.model || 'Codex', effort.name].filter(Boolean).join(' · ') }
  }
  const fam = FAMILIES.find(f => f.match.test(m)) ?? FAMILIES[1]
  const known = MODELS[m]
  const old = /-4-/.test(m)                                        // an older generation: a little smaller
  const price = known?.price ?? 2
  const version = /(\d)-(\d)(?:$|-)/.exec(m)
  return {
    scale: fam.scale - (old ? 0.05 : 0), aura: fam.aura, glow: effort.glow,
    trim: price >= 8 ? GOLD : price >= 4 ? SILVER : price >= 1.5 ? BRONZE : null,
    satchel: (known?.context ?? 1_000_000) >= 1_000_000 ? 2 : 1, gear: fam.gear,
    words: [`${fam.name}${version ? ` ${version[1]}.${version[2]}` : ''}`, effort.name].filter(Boolean).join(' · '),
  }
}
