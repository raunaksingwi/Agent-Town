// The Office look: no map and nobody walking about. Each colony is a cabin: a meeting room with a table,
// its lead at the head and its team seated along both sides, each agent a card with its face, whether it's
// working, asleep or wants you, and what it's on, and the apps the room may use in a grid along its wall.
// The reception holds the mayor, shared files, the library, neighbours' agents and apps nobody uses yet.
// You see one cabin at a time: tabs (or ← →) move between them, and All cabins zooms out to every cabin
// as a small plan, each with who's in it and who wants you. Clicking opens the same panels as on the map
// (App.tsx): an agent's chat, an app's card, a post office.

import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import type { City, Connection, Conversation, MailVisit, MyAgent, PostCount, RunStatus } from './api'
import { preview } from './labels'
import { STATUS_LABEL } from './city/layout'
import { toolLook } from './city/kinds'
import { colonyName, coloniesOf, isMayor, nice } from './colony'
import { Face } from './face'
import { ago } from './time'
import { modalsOpen } from './ui'
import './rooms.css'

type State = 'wants' | 'working' | 'awake' | 'error' | 'asleep'
const LABEL: Record<State, string> = { wants: 'Wants you', working: 'Working', awake: 'Awake', error: 'Something went wrong', asleep: 'Asleep' }

type Props = {
  city: City; awake: Map<number, RunStatus>; convs: Conversation[]; visits: MailVisit[]; posts: Record<string, PostCount>
  selected: string | null; focus: string | null
  onOpen: (key: string) => void                     // agent:1, station:2, post:3, files, library, shared:4
  onMayor: () => void; onVisit: (agentId: number) => void; onColonies: () => void
}
/** A cabin: the reception, a colony's room, a colony with nobody in it yet, or the agents with no team */
type Cabin = { key: string; name: string; about?: string; color: string; lead?: MyAgent; members: MyAgent[]; tools: Connection[]
  post?: { id: number; count?: PostCount }; kind: 'reception' | 'colony' | 'empty' | 'loners' }

export function OfficeRooms(p: Props) {
  const { city } = p
  const mine = city.me ? city.agents : []
  const conns = city.me ? city.connections : []
  const { colonies, loners } = coloniesOf(mine)
  const mayor = mine.find(isMayor)
  const mayorOnly = (c: Connection) => !!mayor && c.granted_to.length > 0 && c.granted_to.every(g => g.agent_id === mayor.id)
  const toolsOf = (team: MyAgent[]) => conns.filter(c => c.granted_to.some(g => team.some(a => a.id === g.agent_id)))
  const unused = conns.filter(c => !mayorOnly(c) && !colonies.some(k => toolsOf([k.lead, ...k.members]).includes(c)) && !toolsOf(loners).includes(c))

  // what each agent is doing, from its run, its chat and its mail
  const seat = (a: MyAgent): { state: State; line: string; visit?: MailVisit } => {
    const visit = p.visits.find(v => v.agent_id === a.id), conv = p.convs.find(c => c.agent.id === a.id)
    const status = p.awake.get(a.id) ?? a.run_status ?? null
    const said = conv?.last ? preview(conv.last, a.description, 'cabin') : ''
    if (visit) return { state: 'wants', line: visit.text, visit }
    if (conv?.waiting) return { state: 'wants', line: `${conv.waiting} waiting for your OK${said ? ` · ${said}` : ''}` }
    if (status === 'busy' || status === 'starting') return { state: 'working', line: status === 'starting' ? 'Waking up…' : said || 'Working on it' }
    if (status === 'ready') return { state: 'awake', line: said || 'Ready to talk' }
    if (status === 'error') return { state: 'error', line: said || 'Open its chat to see what happened' }
    return { state: 'asleep', line: conv?.last ? `${ago(conv.last.created_at)}: ${said}` : 'No chats yet. Click to say hello.' }
  }
  const all = mine.map(a => ({ a, ...seat(a) }))
  const wanting = all.filter(s => s.state === 'wants')

  const seatCard = (a: MyAgent, lead = false) => {
    const key = `agent:${a.id}`, s = seat(a), wants = s.state === 'wants'
    const open = () => isMayor(a) ? p.onMayor() : p.onOpen(key)
    return (
      <article key={a.id} className={`or-seat ${s.state}${p.selected === key ? ' sel' : ''}`} data-key={key} style={{ '--c': a.color } as CSSProperties}>
        <button className="or-seat-open" onClick={open} aria-label={`Talk to ${nice(a.name)}`} />
        <div className="or-who">
          <span className="or-av"><Face slug={a.slug} color={a.color} asleep={s.state === 'asleep'} />
            {wants && <span className="or-flag" aria-hidden>!</span>}</span>
          <span className="or-names"><b>{nice(a.name)}</b><small>{lead ? 'Cabin lead' : a.description}</small></span>
        </div>
        <span className={`or-pill ${s.state}`}><i />{LABEL[s.state]}</span>
        <p className="or-line">{s.line}</p>
        {wants && <button className="or-reply" onClick={s.visit ? () => p.onVisit(a.id) : open}>{s.visit ? 'Hear them out' : 'Review'}</button>}
      </article>
    )
  }

  const toolsBlock = (list: Connection[], title = 'Apps in this room') => !list.length ? null : (
    <div className="or-tools">
      <span className="or-label">{title}</span>
      <div className="or-tool-grid">{list.map(c => {
        const look = toolLook(c), [r, g, b] = look.color, users = mine.filter(a => c.granted_to.some(x => x.agent_id === a.id) && !isMayor(a))
        const bad = c.status === 'error' || c.status === 'auth_required'
        return <button key={c.id} className={`or-tool${p.selected === `station:${c.id}` ? ' sel' : ''}`} data-key={`station:${c.id}`}
          onClick={() => p.onOpen(`station:${c.id}`)} title={`${c.name}: ${STATUS_LABEL[c.status]}${users.length ? ` · used by ${users.map(a => nice(a.name)).join(', ')}` : ''}`}>
          <span className="or-tool-icon" style={{ background: `rgba(${r}, ${g}, ${b}, .16)` }}>{look.icon}</span>
          <span className="or-tool-text"><span className="or-tool-name">{c.name}</span>
            <span className="or-dots">{users.map(a => <i key={a.id} style={{ background: a.color }} />)}</span></span>
          {bad && <span className="or-tool-bad" aria-label={STATUS_LABEL[c.status]} />}
        </button>
      })}</div>
    </div>
  )

  const leaves = (
    <>
      <path d="M24 36C14 30 8 20 10 8C18 14 22 24 24 36Z" fill="#5e8c61" /><path d="M24 36C30 26 38 20 44 18C42 28 34 34 24 36Z" fill="#7ba87e" />
      <path d="M24 36C22 24 26 12 32 4C34 16 30 28 24 36Z" fill="#4c7a50" /><path d="M13 36H35L32 58H16Z" fill="#d9a47e" />
      <rect x="11" y="34" width="26" height="5" rx="2" fill="#c48b63" />
    </>
  )
  const plant = (where = '') => <svg className={`or-plant ${where}`} viewBox="0 0 48 60" aria-hidden="true">{leaves}</svg>

  /** A meeting room: the lead at the head of the table (if it has one), the rest down both sides, left and
   *  right in turn, and a spare seat at the end. */
  const files = city.shared_files.length, library = city.public.filter(s => s.kind === 'file' && s.file).length
  const neighbours = city.public.filter(s => s.kind === 'agent' && s.agent)

  // ---------- the cabins, in order: the reception, each colony, empty colonies, the agents with no team ----------
  const cabins: Cabin[] = [
    { key: 'reception', name: 'Reception', about: 'The mayor, shared files and apps nobody uses yet', color: '#8a7a5c', lead: mayor, members: [], tools: unused, kind: 'reception' },
    ...colonies.map(({ lead, members }): Cabin => ({ key: `colony:${lead.id}`, name: colonyName(lead, 'cabin'), about: lead.colony_about, color: lead.color, lead, members,
      tools: toolsOf([lead, ...members]), post: { id: lead.id, count: p.posts[String(lead.id)] }, kind: 'colony' })),
    ...(city.me ? city.empty_colonies ?? [] : []).map((e, i): Cabin => ({ key: `empty-${i}`, name: e.name, about: e.about || 'No agents yet', color: '#9a9080', members: [], tools: [], kind: 'empty' })),
    ...(loners.length ? [{ key: 'colony:agents', name: colonies.length ? 'More agents' : 'Your agents', about: 'Agents with no team', color: '#8a8478',
      members: loners, tools: toolsOf(loners), kind: 'loners' } as Cabin] : []),
  ]
  const people = (c: Cabin) => [...(c.lead ? [c.lead] : []), ...c.members]
  const wantsIn = (c: Cabin) => people(c).filter(a => seat(a).state === 'wants').length
  /** Which cabin something is in: an agent, an app, the mail, the shelves */
  const cabinOf = (key: string) => {
    const [kind, id] = key.split(':'), n = Number(id)
    if (kind === 'agent') return cabins.find(c => people(c).some(a => a.id === n))
    if (kind === 'station') return cabins.find(c => c.tools.some(t => t.id === n)) ?? cabins[0]
    if (kind === 'post') return cabins.find(c => c.post?.id === n)
    if (kind === 'colony') return cabins.find(c => c.key === key)
    return cabins[0]                                               // files, library, shared, lobby: the reception
  }

  // the cabin you're in, and whether you've zoomed out to all of them; remembered in this browser
  const [cur, setCurState] = useState<string>(() => { try { return localStorage.getItem('agenttown.cabin') ?? 'reception' } catch { return 'reception' } })
  const [overview, setOverview] = useState(false)
  const at = Math.max(0, cabins.findIndex(c => c.key === cur)), here = cabins[at]
  const go = (key: string) => {
    setCurState(key); setOverview(false)
    try { localStorage.setItem('agenttown.cabin', key) } catch { /* private mode */ }
  }
  const step = (d: number) => go(cabins[(at + d + cabins.length) % cabins.length].key)
  // ← and → walk from cabin to cabin, unless you're typing or a window is open over the office
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (overview || modalsOpen() || (e.target as HTMLElement).closest?.('input, textarea, select, [contenteditable]')) return
      if (e.key === 'ArrowRight') step(1); else if (e.key === 'ArrowLeft') step(-1)
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  })

  // the caretaker pointed at something, or you opened it from elsewhere: go to its cabin and show it
  const [flash, setFlash] = useState<string | null>(null)
  useEffect(() => {
    if (!p.focus) return
    const c = cabinOf(p.focus)
    if (c) go(c.key)
    setFlash(p.focus)
  }, [p.focus]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!flash) return
    const el = document.querySelector(`[data-key="${CSS.escape(flash)}"]`) as HTMLElement | null
    if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); el.classList.remove('or-flash'); void el.offsetWidth; el.classList.add('or-flash') }
    setFlash(null)
  }, [flash, cur])

  const first = wanting[0]
  const firstCabin = first && cabinOf(`agent:${first.a.id}`)

  // ---------- one cabin, as you see it ----------
  const head = (c: Cabin) => {
    const mail = c.post?.count && (c.post.count.waiting || c.post.count.threads)
    return <header className="or-room-head">
      <span className="or-swatch" /><h2>{c.name}</h2>
      {c.about && <span className="or-about">{c.about}</span>}
      <span className="grow" />
      {c.post && <button className={`or-post${mail ? ' on' : ''}`} data-key={`post:${c.post.id}`} onClick={() => p.onOpen(`post:${c.post!.id}`)}
        title="This cabin's mail">📮 {c.post.count?.waiting ? `${c.post.count.waiting} waiting` : 'Mail'}</button>}
      {c.kind !== 'reception' && c.kind !== 'empty' && <span className="or-count">{people(c).length} seated</span>}
    </header>
  }
  const windows = <span className="or-windows" aria-hidden>{Array.from({ length: 8 }, (_, i) => <i key={i} />)}</span>

  const cabinView = (c: Cabin): ReactNode => {
    if (c.kind === 'reception') return (
      <section className="or-room reception" data-key="lobby" style={{ '--c': c.color } as CSSProperties}>
        {windows}{head(c)}
        <div className="or-reception">
          <div className="or-desk-area">
            <span className="or-round-rug" aria-hidden />
            {mayor ? seatCard(mayor) : <p className="or-about">The mayor works here once you have one.</p>}
            <span className="or-desk" aria-hidden />
          </div>
          <div className="or-reception-side">
            {(files > 0 || library > 0 || neighbours.length > 0) && <div className="or-tools">
              <span className="or-label">Shelves</span>
              <div className="or-tool-grid">
                {files > 0 && <button className="or-tool" data-key="files" onClick={() => p.onOpen('files')}>
                  <span className="or-tool-icon">🗂</span><span className="or-tool-text"><span className="or-tool-name">Shared files</span><small>{files} files</small></span></button>}
                {library > 0 && <button className="or-tool" data-key="library" onClick={() => p.onOpen('library')}>
                  <span className="or-tool-icon">📚</span><span className="or-tool-text"><span className="or-tool-name">Library</span><small>{library} shared</small></span></button>}
                {neighbours.map(s => <button key={s.id} className="or-tool" data-key={`shared:${s.id}`} onClick={() => p.onOpen(`shared:${s.id}`)}>
                  <span className="or-tool-face"><Face slug={`${s.owner}/${s.agent!.slug}`} color={s.agent!.color} /></span>
                  <span className="or-tool-text"><span className="or-tool-name">{nice(s.agent!.name)}</span><small>@{s.owner}</small></span></button>)}
              </div>
            </div>}
            {toolsBlock(unused, 'Apps nobody uses yet')}
          </div>
        </div>
        {plant()}
      </section>
    )
    if (c.kind === 'empty') return (
      <section className="or-room empty" style={{ '--c': c.color } as CSSProperties}>
        {windows}{head(c)}
        <div className="or-empty"><p>Nobody works here yet.</p><button className="or-spare" onClick={p.onColonies}>+ Seat agents here</button></div>
      </section>
    )
    // a meeting room: the lead at the head of the table, the team along both sides, a spare seat at the end
    const spare = c.kind === 'colony' && c.members.length % 2 === 0
    const half = Math.ceil((c.members.length + (spare ? 1 : 0)) / 2)
    const top = c.members.slice(0, half), bottom = c.members.slice(half)
    return (
      <section className="or-room" data-key={c.key} style={{ '--c': c.color } as CSSProperties}>
        {windows}{head(c)}
        <div className="or-table-area">
          <span className="or-rug" aria-hidden />
          {c.lead && <div className="or-head"><span className="or-label gold">Head of table</span>{seatCard(c.lead, true)}</div>}
          <div className="or-sides">
            <div className="or-side top">{top.map(a => seatCard(a))}</div>
            <div className="or-table" aria-hidden>{Array.from({ length: Math.max(1, half) }, (_, i) =>
              <span key={i} className="or-place"><i className="or-laptop" /><i className="or-mug" /></span>)}</div>
            <div className="or-side bottom">{bottom.map(a => seatCard(a))}
              {spare && <button className="or-spare" onClick={p.onColonies}>+ Add to this team</button>}</div>
          </div>
        </div>
        {toolsBlock(c.tools)}
        {plant('corner tr')}{plant()}
      </section>
    )
  }

  // ---------- every cabin, zoomed out: a small plan of each ----------
  const mini = (a: MyAgent) => {
    const s = seat(a).state
    return <span key={a.id} className={`or-mini-face ${s}`} style={{ '--c': a.color } as CSSProperties} title={`${nice(a.name)}: ${LABEL[s]}`}>
      <Face slug={a.slug} color={a.color} asleep={s === 'asleep'} /></span>
  }
  const tile = (c: Cabin) => {
    const n = wantsIn(c), half = Math.ceil(c.members.length / 2)
    return (
      <button key={c.key} className={`or-tile ${c.kind}${c.key === here.key ? ' here' : ''}`} style={{ '--c': c.color } as CSSProperties} onClick={() => go(c.key)}
        aria-label={`${c.name}${n ? `, ${n} want${n === 1 ? 's' : ''} you` : ''}`}>
        <span className="or-tile-head"><i className="or-swatch" /><b>{c.name}</b><span className="grow" />
          {n > 0 && <span className="or-tile-wants">{n} want{n === 1 ? 's' : ''} you</span>}</span>
        <span className="or-mini">
          {c.kind === 'reception' ? <span className="or-mini-desk">{c.lead && mini(c.lead)}<i /></span>
            : c.kind === 'empty' ? <span className="or-mini-empty">No agents yet</span>
            : <>{c.lead && <span className="or-mini-head">{mini(c.lead)}</span>}
              <span className="or-mini-sides"><span className="or-mini-row">{c.members.slice(0, half).map(mini)}</span><i className="or-mini-table" />
                <span className="or-mini-row">{c.members.slice(half).map(mini)}</span></span></>}
        </span>
        <span className="or-tile-foot">
          <span>{c.kind === 'reception' ? `${files} shared files` : c.kind === 'empty' ? 'Seat agents from Settings → Cabins' : `${people(c).length} seated`}</span>
          <span className="or-tile-apps">{c.tools.slice(0, 6).map(t => <i key={t.id} title={t.name}>{toolLook(t).icon}</i>)}</span>
        </span>
      </button>
    )
  }

  return (
    <main className="or-floor">
      <div className="or-top">
        <h2>Office</h2>
        <span className="or-sub">{colonies.length + (loners.length ? 1 : 0)} cabins · {mine.filter(a => !isMayor(a)).length} agents</span>
        <span className="grow" />
        <span className="or-legend"><i className="working" />Working</span>
        <span className="or-legend"><i className="wants" />Wants you</span>
        <span className="or-legend"><i className="asleep" />Asleep</span>
        {first && firstCabin && <button className="or-wanting" onClick={() => { go(firstCabin.key); setFlash(`agent:${first.a.id}`) }}>
          {wanting.length} want{wanting.length === 1 ? 's' : ''} you</button>}
      </div>
      <nav className="or-tabs" aria-label="Cabins">
        <button className={`or-all${overview ? ' on' : ''}`} onClick={() => setOverview(!overview)} aria-pressed={overview} title="See every cabin at once">
          <span className="or-grid-icon" aria-hidden><i /><i /><i /><i /></span>All cabins</button>
        <span className="or-tab-list" role="tablist">{cabins.map(c => {
          const n = wantsIn(c), on = !overview && c.key === here.key
          return <button key={c.key} role="tab" aria-selected={on} className={`or-tab${on ? ' on' : ''}`} style={{ '--c': c.color } as CSSProperties} onClick={() => go(c.key)}>
            <i className="or-swatch" />{c.name}{n > 0 && <span className="or-tab-wants" aria-label={`${n} want you`}>{n}</span>}</button>
        })}</span>
      </nav>
      {overview
        ? <div className="or-overview">{cabins.map(tile)}</div>
        : <div className="or-stage">
            <button className="or-step prev" onClick={() => step(-1)} aria-label={`Previous: ${cabins[(at - 1 + cabins.length) % cabins.length].name}`}>‹</button>
            <div className="or-cabin" key={here.key}>{cabinView(here)}</div>
            <button className="or-step next" onClick={() => step(1)} aria-label={`Next: ${cabins[(at + 1) % cabins.length].name}`}>›</button>
          </div>}
      {!overview && <p className="or-where">{at + 1} of {cabins.length} · ← → to move between cabins</p>}
    </main>
  )
}
