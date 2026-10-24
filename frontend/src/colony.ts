// Who lives with whom: a colony is a lead and the agents it hands work to (its team). A lead given a colony's
// name with no team yet is a colony of one (backend/app/town.py leads()).
// The map draws each as one block (city/layout.ts); the Colonies panel lists them (colonies.tsx).
// The mayor is in none: it has no house, and walks beside you instead (city/render.ts).

import type { MyAgent } from './api'

export type Colony = { lead: MyAgent; members: MyAgent[] }

// "maya" → "Maya", "chief-of-staff" → "Chief of staff"; a name someone typed stays as they typed it
export const nice = (n: string) => /^[a-z][a-z-]*$/.test(n) ? (n[0].toUpperCase() + n.slice(1)).replace(/-/g, ' ') : n
export const colonyName = (lead: { name: string; colony_name?: string }, word = 'colony') =>   // word: 'cabin' in the Office
  lead.colony_name || `${nice(lead.name.replace(/\s+(lead|head)$/i, ''))}'s ${word}`

export const leads = (a: { team?: number[]; colony_name?: string }) => !!(a.team?.length || a.colony_name)
export const isMayor = (a: { role?: string }) => a.role === 'mayor'
export const agentCount = (n: number) => `${n} agent${n === 1 ? '' : 's'}`

/** Who lives with whom. An agent on several teams joins the first; a lead never joins another colony. */
export function coloniesOf(all: MyAgent[]) {
  const agents = all.filter(a => !isMayor(a))
  const leadOf = new Map<number, MyAgent>()
  for (const a of agents) for (const id of a.team ?? []) { const m = agents.find(m => m.id === id); if (!leadOf.has(id) && m && !leads(m)) leadOf.set(id, a) }
  const colonies: Colony[] = agents.filter(leads).map(lead => ({ lead, members: agents.filter(m => leadOf.get(m.id) === lead) }))
  const loners = agents.filter(a => !leadOf.has(a.id) && !leads(a))
  return { colonies, loners, leadOf }
}
