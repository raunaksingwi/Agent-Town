// The map's two palettes. Everything is drawn in code from these (no image files), in the spirit of a
// 16-bit RPG and a painted fantasy map. The third look, Office, has no map: it's meeting rooms (rooms.tsx,
// look.tsx).

import type { RGB } from './layout'

export type ThemeName = 'retro' | 'fantasy'
export type Theme = {
  name: ThemeName; title: string
  style: 'pixel' | 'soft'                // pixel: crisp scaled pixels; soft: smooth shapes
  res: number                            // offscreen pixels per art pixel
  outline: string | null
  bg: string; grass: RGB[]; dirt: RGB; path: RGB; cobble: RGB; water: RGB; sand: RGB; hedge: RGB
  wall: RGB; stone: RGB; wood: RGB; dark: RGB; glass: RGB; light: RGB
  leaf: RGB[]; trunk: RGB; skin: RGB[]; hair: RGB[]; flowers: RGB[]
  font: (px: number, bold?: boolean) => string
  label: { bg: string; fg: string; sub: string; edge: string }
}

const mono = (px: number, bold = true) => `${bold ? 700 : 500} ${px}px ui-monospace, Menlo, Consolas, monospace`

export const THEMES: Record<ThemeName, Theme> = {
  retro: {
    name: 'retro', title: 'Retro', style: 'pixel', res: 1, outline: '#241f2e',
    bg: '#1e2a44', grass: [[104, 172, 72], [92, 158, 64], [118, 186, 82]], dirt: [186, 144, 96], path: [214, 194, 150],
    cobble: [176, 168, 156], water: [62, 124, 206], sand: [232, 214, 160], hedge: [44, 116, 58],
    wall: [240, 228, 200], stone: [156, 156, 168], wood: [150, 98, 58], dark: [52, 46, 62], glass: [130, 200, 236], light: [255, 226, 120],
    leaf: [[46, 130, 64], [62, 152, 72], [34, 106, 54]], trunk: [112, 72, 44],
    skin: [[248, 208, 168], [226, 174, 130], [180, 122, 86], [122, 82, 58]],
    hair: [[64, 42, 30], [30, 30, 38], [214, 160, 64], [158, 62, 40], [236, 226, 210]],
    flowers: [[240, 80, 90], [250, 220, 80], [240, 240, 255]],
    font: mono, label: { bg: '#fff6dc', fg: '#241f2e', sub: '#6b5a44', edge: '#241f2e' },
  },
  fantasy: {
    name: 'fantasy', title: 'Fantasy', style: 'soft', res: 3, outline: 'rgba(42,28,18,0.6)',
    bg: '#142236', grass: [[92, 150, 72], [80, 136, 64], [106, 166, 82]], dirt: [164, 128, 86], path: [210, 190, 150],
    cobble: [180, 170, 154], water: [38, 110, 168], sand: [222, 204, 160], hedge: [46, 104, 56],
    wall: [234, 218, 186], stone: [162, 158, 150], wood: [142, 96, 58], dark: [46, 40, 50], glass: [150, 210, 240], light: [255, 220, 130],
    leaf: [[52, 122, 62], [68, 142, 68], [40, 100, 54]], trunk: [96, 64, 40],
    skin: [[246, 208, 172], [222, 172, 132], [176, 120, 86], [118, 80, 58]],
    hair: [[70, 44, 30], [34, 30, 36], [222, 172, 80], [160, 66, 44], [238, 230, 214]],
    flowers: [[236, 96, 120], [250, 214, 96], [200, 170, 240]],
    font: (px, bold = true) => `${bold ? 700 : 500} ${px}px Georgia, "Times New Roman", serif`,
    label: { bg: 'rgba(250,240,214,0.94)', fg: '#3a2a1a', sub: '#6b5a44', edge: '#8a6a3a' },
  },
}

