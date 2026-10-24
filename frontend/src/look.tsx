// The look you picked in Settings (Retro, Fantasy or Office) styles everything, not just the map: the
// panels, the chat, the chat app, the title and the fonts. It's kept with your account (map_style), and in
// this browser for when you're signed out. <html data-look="…"> carries it to the CSS (index.css).

import { createContext, useContext, useEffect } from 'react'
import { THEMES, type ThemeName } from './city/themes'

/** A look: one of the map's palettes, or the Office (no map) */
export type Look = ThemeName | 'office'
export const isLook = (s: string | null | undefined): s is Look => !!s && (s === 'office' || s in THEMES)

export const LookContext = createContext<Look>('retro')
export const useLook = () => useContext(LookContext)
/** Office is a work tool: plain words, faces instead of game characters, no houses */
export const usePlain = () => useLook() === 'office'
/** What a team is called: a colony in the town, a cabin in the Office */
export type TeamWord = { one: string; many: string; One: string; Many: string }
export const TEAM_WORDS: Record<'town' | 'office', TeamWord> = {
  town: { one: 'colony', many: 'colonies', One: 'Colony', Many: 'Colonies' },
  office: { one: 'cabin', many: 'cabins', One: 'Cabin', Many: 'Cabins' },
}
export const useTeamWord = () => TEAM_WORDS[usePlain() ? 'office' : 'town']

/** Your look: the one saved with your account, else this browser's, else Retro */
export function lookOf(mapStyle: string | null | undefined): Look {
  if (isLook(mapStyle)) return mapStyle
  try { const t = localStorage.getItem('agenttown.theme'); if (isLook(t)) return t } catch { /* private mode */ }
  return 'retro'
}

/** Put the look on the page, for the CSS */
export function useApplyLook(look: Look) {
  useEffect(() => { document.documentElement.dataset.look = look }, [look])
}
