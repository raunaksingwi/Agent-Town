// Which building each agent and each tool gets, from what it's called and what it does.

export const AGENT_BUILDINGS = {
  studio: 'High-tech studio', office: 'Office', forge: 'Forge (blacksmith)', library: 'Library', lab: 'Lab',
  observatory: 'Observatory', tavern: 'Tavern', cottage: 'Cottage', tower: 'Tower',
} as const
export type AgentBuilding = keyof typeof AGENT_BUILDINGS

export const TOOL_BUILDINGS = {
  stable: 'Post stable', clocktower: 'Clock tower', workshop: 'Workshop', archive: 'Archive',
  signal: 'Signal tower', well: 'Well', barn: 'Barn',
} as const
export type ToolBuilding = keyof typeof TOOL_BUILDINGS

export type BuildingStyle = AgentBuilding | ToolBuilding | 'vault' | 'post'   // post: a colony's post office

const AGENT_RULES: [RegExp, AgentBuilding][] = [
  [/chief|orchestr|manager|\blead|coordinat|boss|strateg|planner|of staff/, 'tower'],
  [/analytic|data|metric|dashboard|report|insight|stats|kpi/, 'observatory'],
  [/code|engineer|develop|\bdev\b|backend|frontend|mobile|\bapi\b|deploy|devops|bug|fix|pr review/, 'forge'],
  [/video|reel|design|creative|instagram|tiktok|photo|\bart\b|brand|youtube|podcast|music/, 'studio'],
  [/experiment|science|research|\bml\b|test|\bqa\b/, 'lab'],
  [/writ|blog|linkedin|newsletter|copy|docs|knowledge|teach|mentor|learn|read/, 'library'],
  [/assistant|personal|errand|inbox|remind|life|home|family|trip|travel/, 'cottage'],
  [/sales|support|customer|community|chat|host|friend/, 'tavern'],
]

export function agentBuilding(a: { building?: string; name: string; description: string }): AgentBuilding {
  if (a.building && a.building in AGENT_BUILDINGS) return a.building as AgentBuilding
  const text = `${a.name} ${a.description}`.toLowerCase()
  return AGENT_RULES.find(([re]) => re.test(text))?.[1] ?? 'office'
}

const TOOL_RULES: [RegExp, ToolBuilding][] = [
  [/mail|outlook|inbox|smtp/, 'stable'],
  [/calendar|\bcal\b|schedul|meeting/, 'clocktower'],
  [/github|gitlab|\bgit\b|linear|jira|sentry|vercel|render/, 'workshop'],
  [/notion|docs|drive|confluence|wiki|sheet|dropbox|file/, 'archive'],
  [/slack|discord|teams|telegram|whatsapp|\bsms\b|twilio|chat/, 'signal'],
  [/postgres|sql|\bdb\b|database|supabase|redis|mongo|bigquery|snowflake/, 'well'],
]

export function toolBuilding(c: { name: string; url: string | null; command: string | null }): ToolBuilding {
  const text = `${c.name} ${c.url ?? ''} ${c.command ?? ''}`.toLowerCase()
  return TOOL_RULES.find(([re]) => re.test(text))?.[1] ?? 'barn'
}

// ---------- what each app looks like: its icon, and a colour close to its own brand ----------
// The same icon is on the app's stall and on every house that may use it, so you can match them up.

export type ToolLook = { icon: string; color: [number, number, number] }

const TOOL_LOOKS: [RegExp, string, [number, number, number]][] = [
  [/gmail|outlook|e-?mail|\bmail\b|inbox/, '✉️', [214, 72, 64]],
  [/calendar|\bcal\b|schedul/, '📅', [66, 133, 244]],
  [/github/, '🐙', [60, 66, 74]],
  [/gitlab/, '🦊', [226, 67, 41]],
  [/linear|jira/, '📋', [94, 106, 210]],
  [/notion|confluence|wiki/, '📒', [70, 70, 70]],
  [/slack|discord|teams|telegram|whatsapp/, '💬', [74, 21, 75]],
  [/posthog|mixpanel|amplitude/, '🦔', [247, 165, 1]],
  [/analytics|plausible|\bga4?\b/, '📈', [242, 153, 0]],
  [/stripe|payment|billing|paddle/, '💳', [99, 91, 255]],
  [/sentry|bugsnag|crash/, '🐞', [54, 45, 89]],
  [/render|vercel|heroku|netlify|fly\.io|aws|gcp|cloud|deploy|hosting/, '☁️', [72, 160, 220]],
  [/intercom|zendesk|helpdesk|support/, '🎧', [31, 140, 235]],
  [/drive|dropbox|box\.com|\bfiles?\b/, '📁', [52, 168, 83]],
  [/youtube/, '▶️', [230, 33, 23]],
  [/instagram/, '📸', [225, 48, 108]],
  [/tiktok/, '🎵', [40, 40, 40]],
  [/figma|canva/, '🎨', [162, 89, 255]],
  [/postgres|mysql|sql|database|\bdb\b|supabase|redis|mongo|bigquery|snowflake/, '🗄️', [51, 103, 145]],
]

export function toolLook(c: { name: string; url: string | null; command: string | null }): ToolLook {
  const text = `${c.name} ${c.url ?? ''} ${c.command ?? ''}`.toLowerCase()
  const hit = TOOL_LOOKS.find(([re]) => re.test(text))
  return hit ? { icon: hit[1], color: hit[2] } : { icon: '🔌', color: [150, 110, 70] }
}

/** Emoji at any size, on a canvas. */
export const EMOJI_FONT = (px: number) => `${px}px "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif`

// ---------- how big an agent's building is, and how it's put together ----------
//
// Everything comes from the agent itself (later: customizable):
//   tier     its "importance": lines of what it knows, plus its tools and files (S, M, L, XL)
//   stories  how many files it has (1–3)
//   tools    the icon of each app it may use, on a side annex (up to 4)
//   banner   a flag on the roof when it's shared publicly

export type HouseSpec = {
  style: AgentBuilding; color: [number, number, number]
  tier: 0 | 1 | 2 | 3; stories: 1 | 2 | 3; tools: ToolLook[]; banner: boolean
}

export function importance(lines: number, files: number, tools: number) {
  return lines + 60 * tools + 40 * files
}

export function houseSpec(a: { lines: number; files: number; tools: ToolLook[]; shared: boolean }, style: AgentBuilding,
  color: [number, number, number]): HouseSpec {
  const score = importance(a.lines, a.files, a.tools.length)
  const tier = (score < 150 ? 0 : score < 500 ? 1 : score < 1500 ? 2 : 3) as HouseSpec['tier']
  const stories = Math.max(1, Math.min(3, Math.ceil(a.files / 3))) as HouseSpec['stories']
  return { style, color, tier, stories, tools: a.tools.slice(0, 4), banner: a.shared }
}

/** Sizes in art pixels (16 per tile): the main body, the annex for tools, and the whole sprite. */
export function houseSize(s: HouseSpec) {
  const body = [48, 64, 80, 96][s.tier]
  const annex = s.tools.length ? (s.tools.length <= 2 ? 16 : 32) : 0
  const wall = 18 + s.stories * 12 + (s.style === 'tower' ? 16 : 0)
  const roof = s.style === 'tower' ? 10 : s.style === 'office' || s.style === 'studio' ? 6 : Math.round(body * 0.36)
  return { body, annex, wall, roof, w: body + annex, h: wall + roof }
}
