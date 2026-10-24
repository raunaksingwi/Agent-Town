// The apps people connect, in their words. Each is an MCP server underneath; most people never need
// to know that. `how` says what connecting takes:
//   oauth  "Sign in with …": the app's own MCP sign-in, as Claude and Codex connectors do
//   token  paste a personal access token; we connect to the app's hosted server with it
//   google "Sign in with Google": Agent Town hosts the tools itself (if this server has a Google client)
//   linkedin "Sign in with LinkedIn": hosted the same way (LinkedIn has no MCP server of its own)
//   soon   its sign-in doesn't work for apps like Agent Town yet
//   custom any MCP server: a URL, a command, or a pasted config (the "Advanced" form)

import type { Connection, MyAgent } from './api'

export type App = {
  key: string; name: string; icon: string; does: string; match: RegExp
  how: 'oauth' | 'token' | 'google' | 'linkedin' | 'soon' | 'custom'
  url?: string; tokenHelp?: string; tokenLink?: string; google?: 'gmail' | 'calendar'
}

export const APPS: App[] = [
  { key: 'gmail', name: 'Gmail', icon: '✉️', does: 'read your email, write drafts, and send only when you press Send (or by rules you set)', match: /gmail|mail|outlook/i, how: 'google', google: 'gmail' },
  { key: 'google-calendar', name: 'Google Calendar', icon: '📅', does: 'see your schedule and add events', match: /calendar|\bcal\b/i, how: 'google', google: 'calendar' },
  { key: 'notion', name: 'Notion', icon: '📒', does: 'read and write your notes and docs', match: /notion/i, how: 'oauth', url: 'https://mcp.notion.com/mcp' },
  { key: 'linear', name: 'Linear', icon: '📋', does: 'see and update your issues', match: /linear/i, how: 'oauth', url: 'https://mcp.linear.app/mcp' },
  { key: 'github', name: 'GitHub', icon: '🐙', does: 'read issues, pull requests and code', match: /github/i, how: 'token',
    url: 'https://api.githubcopilot.com/mcp/', tokenLink: 'https://github.com/settings/personal-access-tokens/new',
    tokenHelp: 'Create a fine-grained token on GitHub with read access to the repositories you want, then paste it here.' },
  { key: 'atlassian', name: 'Jira & Confluence', icon: '🧭', does: 'read and update Jira issues and Confluence pages', match: /atlassian|jira|confluence/i, how: 'oauth', url: 'https://mcp.atlassian.com/v1/mcp' },
  { key: 'sentry', name: 'Sentry', icon: '🛡️', does: 'look into errors and what caused them', match: /sentry/i, how: 'oauth', url: 'https://mcp.sentry.dev/mcp' },
  { key: 'stripe', name: 'Stripe', icon: '💳', does: 'look up customers, payments and subscriptions', match: /stripe/i, how: 'oauth', url: 'https://mcp.stripe.com' },
  { key: 'intercom', name: 'Intercom', icon: '💭', does: 'read customer conversations', match: /intercom/i, how: 'oauth', url: 'https://mcp.intercom.com/mcp' },
  { key: 'monday', name: 'monday.com', icon: '🗂️', does: 'see and update your boards', match: /monday/i, how: 'oauth', url: 'https://mcp.monday.com/mcp' },
  { key: 'canva', name: 'Canva', icon: '🎨', does: 'find and make designs', match: /canva/i, how: 'oauth', url: 'https://mcp.canva.com/mcp' },
  { key: 'vercel', name: 'Vercel', icon: '▲', does: 'check deployments and logs', match: /vercel/i, how: 'oauth', url: 'https://mcp.vercel.com' },
  { key: 'huggingface', name: 'Hugging Face', icon: '🤗', does: 'search models, datasets and papers', match: /hugging ?face/i, how: 'oauth', url: 'https://huggingface.co/mcp' },
  { key: 'linkedin', name: 'LinkedIn', icon: '💼', does: 'post on your LinkedIn as you', match: /linkedin/i, how: 'linkedin' },
  { key: 'slack', name: 'Slack', icon: '💬', does: 'read channels and draft messages', match: /slack/i, how: 'soon' },
  { key: 'postgres', name: 'A database', icon: '🗄️', does: 'answer questions from your data (read-only)', match: /postgres|sql|database|\bdb\b/i, how: 'custom' },
]

/** Off to the app's own sign-in page; it sends you back, and the agent (if any) gets access. */
export function signIn(conn: Connection, agent?: MyAgent) {
  try { if (agent) sessionStorage.setItem('agenttown.resumeSetup', String(agent.id)) } catch { /* private mode */ }
  window.location.href = `/api/connect/mcp/${conn.id}/start${agent ? `?agent=${agent.id}` : ''}`
}

/** "Name: value" (headers) or "KEY=value" (environment) lines into an object; blank lines are skipped. */
export function pairs(text: string, sep: ':' | '='): Record<string, string> {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const i = line.indexOf(sep)
    if (line.trim() && i < 1) throw new Error(`Write each line as ${sep === ':' ? 'Name: value' : 'NAME=value'}: “${line.trim()}”`)
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim()
  }
  return out
}

export const appFor = (key: string) => APPS.find(a => a.key === key)

/** Your existing connection for this app, if you've connected it already. */
export const connectionFor = (app: App, conns: Connection[]) => app.google || app.how === 'linkedin'
  ? conns.find(c => c.app === (app.google ?? 'linkedin')) ?? conns.find(c => !c.app && app.match.test(c.name))   // by what it is, not its name
  : conns.find(c => !c.app && app.match.test(`${c.name} ${c.url ?? ''} ${c.command ?? ''}`))

/** Which apps to suggest for an agent: what its market entry says, else a guess from what it does. */
export function suggestedApps(agent: { name: string; description: string }, marketTools: string[] | undefined): App[] {
  const keys = marketTools?.length ? marketTools : (() => {
    const t = `${agent.name} ${agent.description}`.toLowerCase()
    const out: string[] = []
    if (/mail|inbox|repl/.test(t)) out.push('gmail')
    if (/calendar|meeting|schedul|plan/.test(t)) out.push('google-calendar')
    if (/code|github|pull request|bug|engineer/.test(t)) out.push('github')
    if (/notes|docs|notion|write/.test(t)) out.push('notion')
    if (/issue|ticket|sprint|backlog|project/.test(t)) out.push('linear')
    if (/data|metric|sql|analytic/.test(t)) out.push('postgres')
    if (/linkedin|social|\bposts?\b/.test(t)) out.push('linkedin')
    return out.length ? out : ['gmail', 'google-calendar', 'notion']
  })()
  return keys.map(appFor).filter((a): a is App => !!a)
}
