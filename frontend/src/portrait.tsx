// A character's face for the dialogue box: the same sprite as on the map, drawn big.
// Also used for agents not in your town yet (the market, an import), which have no id or brain.

import { useEffect, useRef } from 'react'
import type { MyAgent } from './api'
import { agentBuilding } from './city/kinds'
import { hex, seedOf } from './city/layout'
import { brainLook } from './city/brain'
import { Paint, drawNpc } from './city/sprites'
import { THEMES } from './city/themes'
import { useLook } from './look'

type Face = Pick<MyAgent, 'slug' | 'name' | 'description' | 'color'> & { id?: number; building?: string; brain?: MyAgent['brain'] }

export function Portrait({ agent, size = 72 }: { agent: Face; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const look = useLook(), theme = THEMES[look === 'fantasy' ? 'fantasy' : 'retro']   // the Office draws faces instead (avatar.tsx)
  useEffect(() => {
    const cv = ref.current!
    const dpr = window.devicePixelRatio || 1
    cv.width = size * dpr; cv.height = size * dpr
    const c = cv.getContext('2d')!
    c.imageSmoothingEnabled = false
    c.scale(dpr, dpr)
    c.fillStyle = '#c9e2f2'; c.fillRect(0, 0, size, size)                    // sky
    c.fillStyle = `rgb(${theme.grass[0].join(',')})`; c.fillRect(0, size * 0.72, size, size * 0.28)   // grass, in the look's colours
    const k = size / 26
    c.translate(size / 2, size * 0.93); c.scale(k, k)
    drawNpc(new Paint(c, theme, agent.id ?? seedOf(agent.slug)), { color: hex(agent.color), seed: seedOf(agent.slug), role: agentBuilding(agent), brain: { ...brainLook(agent.brain), scale: 1 } },
      { dir: 1, step: 0, walking: false, bob: 0, now: 0 })
  }, [agent, size, theme])
  return <canvas ref={ref} className="portrait" style={{ width: size, height: size }} aria-hidden="true" />
}
