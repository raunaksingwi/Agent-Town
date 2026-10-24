// One of your agents. Walking up to it opens a dialogue (chat.tsx). Everything else lives inside its
// house: its instructions on the desk, its files on the bookshelf, what it knows about you on the
// noticeboard, what it remembers in its diary, its apps in the toolbox, its team on the portrait wall, and
// the rest in a chest. In the Office look (look.tsx) there's no house: the same parts are plain tabs.

import { useEffect, useState } from 'react'
import type { Spot } from './access'
import { api, type City, type Connection, type Credential, type FileFull, type EmailPolicy, type Grant, type MyAgent, type RunStatus } from './api'
import { BrainPicker, FileModal, ManifestModal } from './cards'
import { Dialogue } from './chat'
import { AGENT_BUILDINGS, agentBuilding } from './city/kinds'
import { STATUS_LABEL } from './city/layout'
import { useCredentials } from './hooks'
import { usePlain } from './look'
import { nice } from './colony'
import { Err, Md, Modal, msg, readFiles } from './ui'

type Reload = () => Promise<void>

export function AgentView({ agent, city, reload, onClose, onStatus, onTool, onHouse, onSetup, onConnectAi }: {
  agent: MyAgent; city: City; reload: Reload; onClose: () => void; onStatus: (s: RunStatus | null) => void
  onTool: (server: string) => void; onHouse?: (open: boolean) => void; onSetup: () => void; onConnectAi: () => void
}) {
  const [house, setHouse] = useState<Spot | null | false>(false)   // false: outside; null: inside, looking around
  const { creds } = useCredentials()
  const plain = usePlain()
  useEffect(() => { onHouse?.(house !== false) }, [house, onHouse])
  return <>
    <Dialogue key={agent.id} agent={agent} city={city} hasModel={creds === null || creds.length > 0} onStatus={onStatus} onTool={onTool} onTown={reload}
      onHouse={spot => setHouse(spot ?? null)} onSetup={onSetup} onConnectAi={onConnectAi} onClose={onClose} />
    {house !== false && (plain
      ? <Details key={house ?? ''} spot0={house ?? 'desk'} agent={agent} city={city} creds={creds} reload={reload} onSetup={onSetup}
          onClose={() => setHouse(false)} onGone={() => { setHouse(false); onClose() }} />
      : <House key={house ?? ''} spot0={house} agent={agent} city={city} creds={creds} reload={reload} onSetup={onSetup}
          onClose={() => setHouse(false)} onGone={() => { setHouse(false); onClose() }} />)}
  </>
}

function House({ spot0, agent, city, creds, reload, onSetup, onClose, onGone }: {
  spot0: Spot | null; agent: MyAgent; city: City; creds: Credential[] | null; reload: Reload; onSetup: () => void; onClose: () => void; onGone: () => void
}) {
  const [spot, setSpot] = useState<Spot | null>(spot0)
  const about = agent.files.find(f => f.path === 'about-me.md')
  const books = agent.files.filter(f => f.path !== 'AGENT.md' && f.path !== 'about-me.md')
  const shared = city.shared_files ?? []
  const apps = city.connections.filter(c => agent.grants.some(g => g.connection_id === c.id))
  const team = city.agents.filter(a => a.id !== agent.id && agent.team.includes(a.id))

  const furniture: { key: Spot; icon: string; name: string; says: string }[] = [
    { key: 'desk', icon: '📜', name: 'Desk', says: 'its instructions' },
    { key: 'books', icon: '📚', name: 'Bookshelf', says: `${books.length + shared.length} book${books.length + shared.length === 1 ? '' : 's'}` },
    { key: 'board', icon: '📌', name: 'Noticeboard', says: about ? 'what it knows about you' : 'nothing about you yet' },
    { key: 'diary', icon: '📓', name: 'Diary', says: agent.memory.trim() ? 'what it remembers' : 'remembers nothing yet' },
    { key: 'tools', icon: '🛠️', name: 'Tools', says: apps.length ? apps.map(a => a.name).join(', ') : 'no apps yet' },
    { key: 'team', icon: '🖼️', name: 'Portraits', says: team.length ? `its team of ${team.length}` : 'works alone' },
    { key: 'chest', icon: '🧰', name: 'Chest', says: 'its brain and settings' },
  ]

  return (
    <Modal title={`Inside ${agent.name}'s house`} onClose={onClose} wide>
      <div className="room">
        {furniture.map(f => (
          <button key={f.key} className={`furniture${spot === f.key ? ' on' : ''}`} onClick={() => setSpot(spot === f.key ? null : f.key)}>
            <span className="f-icon" aria-hidden="true">{f.icon}</span><b>{f.name}</b><span className="f-says">{f.says}</span>
          </button>))}
      </div>
      {!spot && <p className="hint room-hint">Look around: click anything in the room.</p>}
      {spot && <AgentSection spot={spot} agent={agent} city={city} creds={creds} reload={reload} onSetup={onSetup} onGone={onGone} />}
    </Modal>
  )
}

const DETAILS: { key: Spot; label: string }[] = [
  { key: 'desk', label: 'Instructions' }, { key: 'books', label: 'Knowledge' }, { key: 'board', label: 'About you' },
  { key: 'diary', label: 'Memory' }, { key: 'tools', label: 'Apps' }, { key: 'team', label: 'Team' }, { key: 'chest', label: 'Settings' },
]

/** The Office's version of the house: the same parts, as tabs with plain names. */
function Details({ spot0, agent, city, creds, reload, onSetup, onClose, onGone }: {
  spot0: Spot; agent: MyAgent; city: City; creds: Credential[] | null; reload: Reload; onSetup: () => void; onClose: () => void; onGone: () => void
}) {
  const [spot, setSpot] = useState<Spot>(spot0)
  return (
    <Modal title={nice(agent.name)} onClose={onClose} wide>
      <div className="details-tabs" role="tablist">{DETAILS.map(t =>
        <button key={t.key} role="tab" aria-selected={spot === t.key} className={spot === t.key ? 'on' : ''} onClick={() => setSpot(t.key)}>{t.label}</button>)}</div>
      <AgentSection spot={spot} agent={agent} city={city} creds={creds} reload={reload} onSetup={onSetup} onGone={onGone} plain />
    </Modal>
  )
}

/** One part of an agent: its instructions, files, what it knows about you, memory, apps, team or settings.
    Shown inside its house on the map, or as a plain tab in the workspace (`plain`: plain names, no map). */
export function AgentSection({ spot, agent, city, creds, reload, onSetup, onGone, plain }: {
  spot: Spot; agent: MyAgent; city: City; creds: Credential[] | null; reload: Reload; onSetup: () => void; onGone: () => void; plain?: boolean
}) {
  const [open, setOpen] = useState<FileFull | null>(null)
  const [manifest, setManifest] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [diary, setDiary] = useState<string | null>(null)   // being edited

  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await reload() } catch (e) { setError(msg(e)) }
  }

  const grants = agent.grants
  const has = (c: Connection, tool: string | null) => grants.some(g => g.connection_id === c.id && g.tool_name === tool)
  const toggleTool = (c: Connection, tool: string) => {
    let next: Grant[]
    if (has(c, null)) next = [...grants.filter(g => g.connection_id !== c.id),                       // all but this one
      ...c.tools.filter(x => x.name !== tool).map(x => ({ connection_id: c.id, tool_name: x.name }))]
    else if (has(c, tool)) next = grants.filter(g => !(g.connection_id === c.id && g.tool_name === tool))
    else next = [...grants, { connection_id: c.id, tool_name: tool }]
    run(() => api.setGrants(agent.id, next))
  }

  const definition = agent.files.find(f => f.path === 'AGENT.md')
  const about = agent.files.find(f => f.path === 'about-me.md')
  const books = agent.files.filter(f => f.path !== 'AGENT.md' && f.path !== 'about-me.md')
  const shared = city.shared_files ?? []
  const others = city.agents.filter(a => a.id !== agent.id)
  const cred = creds && (creds.find(c => c.id === agent.model_credential_id) ?? creds.find(c => c.is_default))
  const claude = !cred || cred.provider === 'anthropic'
  const T = plain
    ? { desk: 'Instructions', books: 'Knowledge files', board: 'About you', diary: 'Memory', tools: 'Apps and permissions', team: 'Team', brain: 'Model' }
    : { desk: 'Its instructions', books: 'Bookshelf', board: 'Noticeboard: about you', diary: 'Diary: what it remembers', tools: 'Tools: apps it can use', team: 'Portrait wall: its team', brain: 'Its brain' }

  return <>
      {spot === 'desk' && definition && <section className="spot">
        <h3>{T.desk}</h3>
        <p className="hint">This is who {agent.name} is and how it works. Change it if you like; it takes effect next chat.</p>
        {plain && <div className="pinned"><Md text={definition.content} /></div>}
        <button className="primary" onClick={() => setOpen(definition)}>{plain ? 'Edit' : 'Read or edit'} ({definition.lines} lines)</button>
      </section>}

      {spot === 'books' && <section className="spot">
        <h3>{T.books}</h3>
        {books.length === 0 && shared.length === 0 && <p className="empty">No books yet. Add notes, playbooks or examples it should read.</p>}
        <ul className="list">
          {[...books].sort((a, b) => b.lines - a.lines).map(f => (
            <li key={f.id}><button className="rowbtn grow" onClick={() => setOpen(f)}><span className="grow">{!plain && '📕 '}{f.path}</span><span className="meta">{f.lines} lines</span></button>
              <button className="tiny" title={`Delete ${f.path}`} aria-label={`Delete ${f.path}`} onClick={() => { if (confirm(`Delete ${f.path}?`)) run(() => api.deleteFile(agent.id, f.id)) }}>✕</button></li>))}
          {shared.map(f => <li key={`s${f.id}`} className="nohover"><span className="grow">{!plain && '📗 '}{f.path}</span><span className="meta">shared, all your agents</span></li>)}
        </ul>
        <label className="linklike">+ put a book on the shelf
          <input type="file" multiple accept=".md,.txt" hidden onChange={async e => {
            const files = await readFiles(e.target.files)
            run(async () => { for (const f of files) await api.putFile(agent.id, f.path, f.content) })
          }} /></label>
      </section>}

      {spot === 'board' && <section className="spot">
        <h3>{T.board}</h3>
        {about ? <div className="pinned"><Md text={about.content} /></div> : <p className="empty">{agent.name} doesn't know anything about you yet.</p>}
        <button className="primary" onClick={onSetup}>{about ? 'Change what it knows' : 'Tell it about you'}</button>
      </section>}

      {spot === 'diary' && <section className="spot">
        <h3>{T.diary}</h3>
        <p className="hint">{agent.name} keeps these notes between chats, and also reads what was said in its last few chats.
          Change anything that's wrong; it takes effect next chat.</p>
        {diary !== null ? <>
          <textarea className="editor" value={diary} onChange={e => setDiary(e.target.value)} rows={14} maxLength={20000} />
          <div className="row"><button className="primary" onClick={() => run(async () => { await api.updateAgent(agent.id, { memory: diary }); setDiary(null) })}>Save</button>
            <button onClick={() => setDiary(null)}>Cancel</button></div>
        </> : <>
          {agent.memory.trim() ? <div className="pinned"><Md text={agent.memory} /></div>
            : <p className="empty">Nothing yet. As you chat, {agent.name} writes down what's worth remembering.</p>}
          <div className="row">
            <button onClick={() => setDiary(agent.memory)}>{agent.memory.trim() ? 'Edit' : 'Write something'}</button>
            {agent.memory.trim() && <button className="danger" onClick={() => {
              if (confirm(`Make ${agent.name} forget everything in its diary?`)) run(() => api.updateAgent(agent.id, { memory: '' }))
            }}>Forget everything</button>}
          </div>
        </>}
      </section>}

      {spot === 'tools' && <section className="spot">
        <h3>{T.tools}</h3>
        {city.connections.length === 0 ? <p className="empty">No apps connected yet. Use <b>Settings</b> → <b>Connect apps</b> (under your name, top right), or <b>Make it your own</b>.</p> :
          <ul className="list tools">{city.connections.map(c => {
            const any = grants.some(g => g.connection_id === c.id)
            return <li key={c.id} className="tool">
              <label className="grow"><input type="checkbox" checked={any}
                onChange={() => run(() => api.setGrants(agent.id, any ? grants.filter(g => g.connection_id !== c.id) : [...grants, { connection_id: c.id, tool_name: null }]))} />
                <b>{c.name}</b> <span className={`dot ${c.status}`} /> <span className="meta">{STATUS_LABEL[c.status]}</span></label>
              {any && c.tools.length > 0 && <details><summary className="meta">which of its tools</summary><div className="subtools">
                {c.tools.map(t => <label key={t.name} title={t.description}>
                  <input type="checkbox" checked={has(c, null) || has(c, t.name)} onChange={() => toggleTool(c, t.name)} />{t.name}</label>)}</div></details>}
            </li>
          })}</ul>}
        {city.connections.some(c => c.app === 'gmail' && (has(c, null) || has(c, 'send_email'))) && <EmailRules key={agent.email_policy.allow.join()} agent={agent} run={run} />}
        {city.connections.some(c => c.app === 'linkedin' && (has(c, null) || has(c, 'create_post'))) && <PostRules agent={agent} run={run} />}
      </section>}

      {spot === 'team' && <section className="spot">
        <h3>{T.team}</h3>
        {others.length === 0 ? <p className="empty">Add more agents and {agent.name} can hand work to them.</p> : <>
          <ul className="list tools">{others.map(o => (
            <li key={o.id} className="tool"><label className="grow"><input type="checkbox" checked={agent.team.includes(o.id)}
              onChange={() => run(() => api.setTeam(agent.id, agent.team.includes(o.id) ? agent.team.filter(i => i !== o.id) : [...agent.team, o.id]))} />
              <b>{o.name}</b> <span className="meta wrap">{o.description.slice(0, 80)}</span></label></li>))}</ul>
          <p className="hint">It can hand a job to anyone ticked here.{!claude && ' Needs a Claude model: on ChatGPT it works alone.'}</p>
        </>}
      </section>}

      {spot === 'chest' && <section className="spot">
        <h3>{T.brain}</h3>
        <BrainPicker agent={agent} run={run} />
        {!plain && <><h3>Its house on the map</h3>
        <div className="row tight">
          <select value={agent.building || ''} onChange={e => run(() => api.updateAgent(agent.id, { building: e.target.value }))}>
            <option value="">Automatic ({AGENT_BUILDINGS[agentBuilding({ ...agent, building: '' })]})</option>
            {Object.entries(AGENT_BUILDINGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div></>}
        <h3>Sharing</h3>
        <label className="check"><input type="checkbox" checked={agent.can_use_public}
          onChange={e => run(() => api.updateAgent(agent.id, { can_use_public: e.target.checked }))} />
          May read what other people shared publicly</label>
        <div className="row">
          {agent.share_id
            ? <button onClick={() => run(() => api.unshare(agent.share_id!))}>Make private</button>
            : <><input className="note" placeholder="Note for others (optional)" value={note} onChange={e => setNote(e.target.value)} />
              <button onClick={() => run(() => api.share({ kind: 'agent', agent_id: agent.id, note }))}>Share publicly</button></>}
        </div>
        <div className="row">
          <button onClick={() => setManifest(true)} title="Exactly what its sandbox is handed">Under the hood</button>
          <span className="grow" />
          <button className="danger" onClick={() => { if (confirm(`Delete ${agent.name} and its house?`)) run(async () => { await api.deleteAgent(agent.id); onGone() }) }}>Delete {agent.name}</button>
        </div>
      </section>}

      <Err error={error} />
      {open && <FileModal file={open} editable onClose={() => setOpen(null)}
        onSave={async content => { await api.putFile(agent.id, open.path, content); await reload(); setOpen(null) }} />}
      {manifest && <ManifestModal agentId={agent.id} onClose={() => setManifest(false)} />}
  </>
}

/** When an email it sends may go out without your Send. Checked by Agent Town, not by the agent
    (backend/app/outbox.py), so changes count at once, even mid-chat. */
function EmailRules({ agent, run }: { agent: MyAgent; run: (fn: () => Promise<unknown>) => void }) {
  const p = agent.email_policy
  const [allow, setAllow] = useState(p.allow.join(', '))
  const save = (patch: Partial<EmailPolicy>) => run(() => api.updateAgent(agent.id, { email_policy: { ...p, ...patch } }))
  const list = (t: string) => t.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean)
  return <div className="email-rules">
    <h3>Sending email</h3>
    <label className="check"><input type="radio" checked={p.mode === 'ask'} onChange={() => save({ mode: 'ask' })} />
      Ask me every time</label>
    <label className="check"><input type="radio" checked={p.mode === 'auto'} onChange={() => save({ mode: 'auto' })} />
      Send on its own when…</label>
    {p.mode === 'auto' && <div className="indent">
      <label className="check"><input type="radio" checked={p.to === 'known'} onChange={() => save({ to: 'known' })} />
        it's to people I've emailed before, or to these addresses or domains:</label>
      <input className="note" placeholder="acme.com, sam@example.com" value={allow} disabled={p.to !== 'known'}
        onChange={e => setAllow(e.target.value)}
        onBlur={() => { if (list(allow).join(',') !== p.allow.join(',')) save({ allow: list(allow) }) }} />
      <label className="check"><input type="radio" checked={p.to === 'anyone'} onChange={() => {
        if (confirm(`Let ${agent.name} email anyone without asking? An email from a stranger could trick it into writing to someone you don't know.`)) save({ to: 'anyone' })
      }} />it's to anyone <span className="meta warn">(risky)</span></label>
      <label className="check"><input type="checkbox" checked={p.replies_only} onChange={e => save({ replies_only: e.target.checked })} />
        and it's a reply in an existing thread</label>
      <p className="hint">Either way, it waits 2 minutes so you can cancel it (in the chat or on Today), and no more than 10 a
        day go out on their own. If, in that chat, it read an email from someone you haven't written to, another app's
        results or the web, it asks you instead: that's how a stranger's email could try to give it orders.</p>
    </div>}
  </div>
}

/** Whether a LinkedIn post it writes goes out at once or waits for your Post (backend/app/outbox.py). */
function PostRules({ agent, run }: { agent: MyAgent; run: (fn: () => Promise<unknown>) => void }) {
  const save = (mode: 'ask' | 'auto') => run(() => api.updateAgent(agent.id, { post_policy: { mode } }))
  return <div className="email-rules">
    <h3>Posting on LinkedIn</h3>
    <label className="check"><input type="radio" checked={agent.post_policy.mode === 'auto'} onChange={() => save('auto')} />
      Post on its own</label>
    <label className="check"><input type="radio" checked={agent.post_policy.mode === 'ask'} onChange={() => save('ask')} />
      Ask me first</label>
    <p className="hint">On its own, a post goes out the moment {agent.name} writes it (you can delete it on LinkedIn), and
      after 5 in a day it asks you instead.</p>
  </div>
}
