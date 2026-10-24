// An agent's picture wherever it appears in a list or a chat: its game character on the map's looks, its
// drawn face in the Office (look.tsx).

import type { CSSProperties } from 'react'
import type { MyAgent } from './api'
import { Face } from './face'
import { usePlain } from './look'
import { Portrait } from './portrait'

type Who = Pick<MyAgent, 'slug' | 'name' | 'description' | 'color'> & { id?: number; building?: string; brain?: MyAgent['brain'] }

export function Avatar({ agent, size = 72, asleep }: { agent: Who; size?: number; asleep?: boolean }) {
  if (!usePlain()) return <Portrait agent={agent} size={size} />
  return <span className="avatar-face" style={{ width: size, height: size, '--c': agent.color } as CSSProperties} aria-hidden="true">
    <Face slug={agent.slug} color={agent.color} asleep={asleep} /></span>
}
