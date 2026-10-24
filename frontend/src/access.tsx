// What an agent can reach, at a glance: shown as soon as you click it. Each chip opens a short list
// (which of an app's tools, which files, who's on its team) with a way into the right corner of its house.

import type { City, Connection, MyAgent } from './api'
import { APPS } from './connectors'
import { brainLook } from './city/brain'
import { STATUS_LABEL } from './city/layout'

export type Spot = 'desk' | 'books' | 'board' | 'diary' | 'tools' | 'team' | 'chest'

const appIcon = (c: Connection) =>
  c.app === 'gmail' ? '✉️' : c.app === 'calendar' ? '📅' : c.app === 'linkedin' ? '💼' : APPS.find(a => !a.google && a.match.test(`${c.name} ${c.url ?? ''}`))?.icon ?? '🔌'
const usable = (c: Connection) => c.status === 'connected' || c.status === 'needs_sandbox'

type Chip = { key: string; icon: string; label: string; spot: Spot; warn?: boolean; title: string; body: React.ReactNode; change: string }

function chips(agent: MyAgent, city: City): Chip[] {
  const out: Chip[] = []
  const apps = city.connections.filter(c => agent.grants.some(g => g.connection_id === c.id))
  for (const c of apps) {
    const all = agent.grants.some(g => g.connection_id === c.id && g.tool_name === null)
    const picked = all ? c.tools.map(t => t.name) : agent.grants.filter(g => g.connection_id === c.id).map(g => g.tool_name!)
    const count = all ? 'all tools' : `${picked.length} of ${c.tools.length || picked.length}`
    out.push({ key: `app:${c.id}`, icon: appIcon(c), label: `${c.name} · ${count}`, spot: 'tools', warn: !usable(c),
      title: `${c.name}: ${all ? 'every tool' : `${picked.length} tool${picked.length === 1 ? '' : 's'}`}`, change: 'Change its apps',
      body: <>
        <p className="hint"><span className={`dot ${c.status}`} /> {STATUS_LABEL[c.status]}
          {!usable(c) && ` — ${agent.name} can't use it until it's connected. Click the ${c.name} building to fix it.`}</p>
        {picked.length ? <ul className="access-list">{picked.map(name => {
          const t = c.tools.find(x => x.name === name)
          return <li key={name}><b className="mono">{name}</b>{t?.description && <span className="meta"> {t.description.split('\n')[0].slice(0, 120)}</span>}</li>
        })}</ul> : <p className="empty">Its tools are listed once it has run in a sandbox.</p>}
      </> })
  }
  if (!apps.length) out.push({ key: 'apps', icon: '🔌', label: 'No apps', spot: 'tools', title: 'No apps', change: 'Give it apps',
    body: <p className="empty">{agent.name} can't reach any of your apps yet: only its files and what you tell it.</p> })

  const books = agent.files.filter(f => f.path !== 'about-me.md')
  const shared = city.shared_files ?? []
  const about = agent.files.find(f => f.path === 'about-me.md')
  out.push({ key: 'files', icon: '📚', label: `${books.length + shared.length} file${books.length + shared.length === 1 ? '' : 's'}`, spot: 'books',
    title: 'Files it reads', change: 'Add or change files',
    body: <ul className="access-list">
      {books.map(f => <li key={f.id}>{f.path === 'AGENT.md' ? '📜' : '📕'} {f.path}<span className="meta"> · {f.path === 'AGENT.md' ? 'its instructions' : `${f.lines} lines`}</span></li>)}
      {shared.map(f => <li key={`s${f.id}`}>📗 {f.path}<span className="meta"> · shared with all your agents</span></li>)}
      <li>📌 about-me.md<span className="meta"> · {about ? 'what it knows about you' : 'nothing about you yet'}</span></li>
    </ul> })

  if (agent.memory.trim()) out.push({ key: 'memory', icon: '📓', label: 'Its notes', spot: 'diary', title: 'What it remembers', change: 'Read or edit its diary',
    body: <><p className="hint">It reads these, and its last few chats, every time it wakes up.</p>
      <p className="access-quote">{agent.memory.trim().slice(0, 400)}{agent.memory.trim().length > 400 ? '…' : ''}</p></> })

  const team = city.agents.filter(a => agent.team.includes(a.id))
  if (team.length) out.push({ key: 'team', icon: '👥', label: `Team of ${team.length}`, spot: 'team', title: 'Who it can hand work to', change: 'Change its team',
    body: <ul className="access-list">{team.map(a => <li key={a.id}><b>{a.name}</b><span className="meta"> {a.description.slice(0, 90)}</span></li>)}</ul> })

  if (agent.can_use_public) {
    const pub = city.public.filter(s => s.allow_agent_use && s.owner !== city.me?.username)
    out.push({ key: 'public', icon: '🌐', label: 'Public shelf', spot: 'chest', title: 'What other people shared', change: 'Change',
      body: <p className="hint">It may read what other people shared for agents to use: {pub.length ? `${pub.length} item${pub.length === 1 ? '' : 's'} right now` : 'nothing right now'}.</p> })
  }

  const look = brainLook(agent.brain)
  out.push({ key: 'brain', icon: '🧠', label: agent.brain ? look.words : 'No AI account', spot: 'chest', warn: !agent.brain, title: 'What it thinks with',
    change: 'Change its brain',
    body: agent.brain ? <p className="hint">{look.words}, on your {agent.brain.provider === 'openai' ? 'ChatGPT' : 'Claude'} account.</p>
      : <p className="empty">It needs an AI account to think with: add one in Settings (under your name, top right) → Account and AI models.</p> })
  return out
}

export function Access({ agent, city, open, setOpen, onChange }: {
  agent: MyAgent; city: City; open: string | null; setOpen: (k: string | null) => void; onChange: (spot: Spot) => void
}) {
  const list = chips(agent, city)
  const cur = list.find(c => c.key === open)
  return <>
    <div className="access" aria-label={`What ${agent.name} can use`}>
      <span className="access-head">Can use</span>
      {list.map(c => <button key={c.key} className={`chip${c.key === open ? ' on' : ''}${c.warn ? ' warn' : ''}`} aria-expanded={c.key === open}
        onClick={() => setOpen(c.key === open ? null : c.key)}><span aria-hidden="true">{c.icon}</span> {c.label}</button>)}
    </div>
    {cur && <div className="access-detail">
      <div className="access-title"><b>{cur.icon} {cur.title}</b><span className="grow" />
        <button className="tiny" onClick={() => onChange(cur.spot)}>{cur.change}</button>
        <button className="x" onClick={() => setOpen(null)} aria-label="Close">×</button></div>
      {cur.body}
    </div>}
  </>
}
