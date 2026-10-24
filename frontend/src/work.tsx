// The workspace (/work): the same agents, apps and routines as the town, laid out like a work tool.
// A sidebar of agents grouped by team, and plain pages: Home (what's waiting on you), Agents (a table),
// one agent (chat, instructions, files, memory, apps, team, settings as tabs), Apps and Shared files.
// No map and no metaphors: every label names the thing it is. The town at / is unchanged; which one
// opens is remembered in this browser (main.tsx).

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type City, type Conversation, type MyAgent, type RunStatus } from './api'
import type { Spot } from './access'
import { AgentSection } from './agent'
import { SharedFilesCard } from './cards'
import { ThreadView } from './chatapp'
import { colonyName, coloniesOf, leads, nice } from './colony'
import { ColoniesModal } from './colonies'
import { ConnectAiModal } from './connect-ai'
import { forgetCredentials, invalidateCredentials, useCredentials, useGoogleReturn, usePoll, useSignInReturn, useUnauthenticated, type Notice } from './hooks'
import { AddModal } from './importer'
import { RUN_STATUS_PLAIN as STATUS } from './labels'
import { AuthModal, NewAgentModal, NewToolModal } from './modals'
import { AccountModal } from './account'
import { ProfileModal } from './profile'
import { AppList, SetupModal } from './setup'
import { TodayView } from './today'
import { msg } from './ui'
import { POLL } from './ui-constants'
import { WelcomeModal } from './welcome'
import './work.css'

type Tab = 'chat' | Spot
type Page = { kind: 'home' } | { kind: 'agents' } | { kind: 'agent'; id: number; tab: Tab } | { kind: 'apps' } | { kind: 'files' }

const TABS: { key: Tab; label: string }[] = [
  { key: 'chat', label: 'Chat' }, { key: 'desk', label: 'Instructions' }, { key: 'books', label: 'Knowledge' },
  { key: 'board', label: 'About you' }, { key: 'diary', label: 'Memory' }, { key: 'tools', label: 'Apps' },
  { key: 'team', label: 'Team' }, { key: 'chest', label: 'Settings' },
]
const SPOTS: Record<string, Tab> = { chat: 'chat', instructions: 'desk', knowledge: 'books', about: 'board', memory: 'diary', apps: 'tools', team: 'team', settings: 'chest' }
const slugOf = (t: Tab) => Object.keys(SPOTS).find(k => SPOTS[k] === t) ?? 'chat'

function fromUrl(): Page {
  const p = location.pathname.replace(/^\/work\/?/, '').split('/').filter(Boolean)
  if (p[0] === 'agents' && p[1]) return { kind: 'agent', id: Number(p[1]), tab: SPOTS[p[2] ?? 'chat'] ?? 'chat' }
  if (p[0] === 'agents') return { kind: 'agents' }
  if (p[0] === 'apps') return { kind: 'apps' }
  if (p[0] === 'files') return { kind: 'files' }
  return { kind: 'home' }
}
function toUrl(p: Page): string {
  return p.kind === 'agent' ? `/work/agents/${p.id}/${slugOf(p.tab)}` : p.kind === 'home' ? '/work' : `/work/${p.kind}`
}

/** Back to the map, for good in this browser (main.tsx reads it) */
function toTown() {
  try { localStorage.setItem('agenttown.ui', 'town') } catch { /* private mode */ }
  location.href = '/'
}

export function Workspace() {
  const [city, setCity] = useState<City | null>(null)
  const [page, setPage] = useState<Page>(fromUrl)
  const [down, setDown] = useState<string | null>(null)   // the API couldn't be reached: why
  const [convs, setConvs] = useState<Conversation[]>([])
  const [awake, setAwake] = useState<Map<number, RunStatus>>(new Map())
  const { creds } = useCredentials()
  const signin = useGoogleReturn()
  const [modal, setModal] = useState<'login' | 'signup' | 'add' | 'agent' | 'tool' | 'account' | 'profile' | 'ai' | 'colonies' | null>(signin.error ? 'login' : null)
  const [setup, setSetup] = useState<{ id: number; step: number } | null>(null)
  const [welcome, setWelcome] = useState<boolean | null>(null)
  const [notice, setNotice] = useState<Notice>(null)
  const [navOpen, setNavOpen] = useState(false)      // phones: the sidebar slides over the page

  const reload = useCallback(async () => {
    try { setCity(await api.city()); setDown(null) } catch (e) { setDown(msg(e)) }
  }, [])
  useEffect(() => { reload() }, [reload])
  useUnauthenticated(() => {                         // the session expired: back to the sign-in
    if (!city?.me) return
    forgetCredentials(); setSetup(null); setNotice({ ok: false, text: 'Your session expired. Sign in again.' }); reload()
  })
  useEffect(() => {
    const back = () => setPage(fromUrl())
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
  const go = (p: Page) => { history.pushState(null, '', toUrl(p)); setPage(p); setNavOpen(false) }

  // back from a sign-in (Google's, or an app's): say how it went, and pick up setup where it was (as App does)
  useSignInReturn(setNotice, id => setSetup({ id, step: 1 }))

  const me = city?.me
  // who's working, and what's waiting on you, for the sidebar
  usePoll(() => Promise.all([
    api.awake().then(a => setAwake(new Map(a.map(x => [x.agent_id, x.status]))), () => {}),
    api.conversations().then(setConvs, () => {}),
  ]), () => POLL.workspace, [me?.id], !!me)
  useEffect(() => { if (city?.me && welcome === null) setWelcome(city.agents.length === 0) }, [city, welcome])

  const openAgent = (id: number, tab: Tab = 'chat') => go({ kind: 'agent', id, tab })
  const startWith = (id: number) => { setWelcome(false); openAgent(id); setSetup({ id, step: 1 }) }
  // a new account from Google starts like one from the form: on its assistant's apps
  const startedNew = useRef(false)
  useEffect(() => {
    if (!signin.isNew || startedNew.current || !city?.me) return
    startedNew.current = true
    const assistant = city.agents.find(a => a.slug === 'ava')
    if (assistant) startWith(assistant.id)
  }, [city]) // eslint-disable-line react-hooks/exhaustive-deps
  const connectAi = () => setModal('ai')

  if (!city) return <div className="ws-loading">{down && <div className="ws-emptybox" role="alert">
    <b>Can't reach Agent Town.</b><p className="hint">{down}</p><button className="primary" onClick={reload}>Retry</button></div>}</div>
  if (!me) return <div className="ws-signin">
    <h1>Agent Town</h1>
    <p className="hint">AI agents that work for you: they read your mail and calendar, draft replies, run routines, and wait for your OK before anything goes out.</p>
    <div className="row center"><button className="primary" onClick={() => setModal('signup')}>Create account</button>
      <button onClick={() => setModal('login')}>Sign in</button></div>
    <p className="hint"><a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></p>
    {(modal === 'login' || modal === 'signup') && <AuthModal mode={modal} error={signin.error} onClose={() => setModal(null)}
      onDone={async m => {
        setModal(null); forgetCredentials()
        try {
          const c = await api.city()
          setCity(c); setDown(null)
          const assistant = m === 'signup' ? c.agents.find(a => a.slug === 'ava') : undefined
          if (assistant) startWith(assistant.id)
        } catch (e) { setDown(msg(e)) }
      }} />}
  </div>

  const waiting = new Map(convs.map(c => [c.agent.id, c.waiting]))
  const totalWaiting = convs.reduce((n, c) => n + c.waiting, 0)
  const status = (id: number): RunStatus | null => awake.get(id) ?? null
  const { colonies, loners } = coloniesOf(city.agents)
  const agent = page.kind === 'agent' ? city.agents.find(a => a.id === page.id) : undefined
  const setupAgent = setup ? city.agents.find(a => a.id === setup.id) : undefined
  const noAi = creds !== null && creds.length === 0

  const navItem = (p: Page, label: string, count?: number) =>
    <button className={page.kind === p.kind ? 'on' : ''} onClick={() => go(p)}>
      <span className="grow">{label}</span>{!!count && <span className="ws-count">{count}</span>}</button>
  const agentItem = (a: MyAgent, sub?: boolean) =>
    <button key={a.id} className={`${agent?.id === a.id ? 'on' : ''}${sub ? ' sub' : ''}`} onClick={() => openAgent(a.id)}>
      <Avatar a={a} size={18} /><span className="grow ellipsis">{nice(a.name)}</span>
      {!!waiting.get(a.id) && <span className="ws-count">{waiting.get(a.id)}</span>}
      <Dot s={status(a.id)} quiet /></button>

  return <div className={`ws${navOpen ? ' nav-open' : ''}`}>
    <aside className="ws-side">
      <div className="ws-brand">Agent Town</div>
      <nav className="ws-nav">
        {navItem({ kind: 'home' }, 'Home', totalWaiting)}
        {navItem({ kind: 'agents' }, 'Agents')}
        {navItem({ kind: 'apps' }, 'Apps')}
        {navItem({ kind: 'files' }, 'Shared files')}
      </nav>
      <div className="ws-label"><span className="grow">Agents</span>
        <button className="ws-icon" title="Add agents" aria-label="Add agents" onClick={() => setModal('add')}>+</button></div>
      <nav className="ws-nav">
        {colonies.map(c => <div key={c.lead.id} className="ws-team">
          <div className="ws-team-name">{colonyName(c.lead)}</div>
          {agentItem(c.lead)}
          {c.members.map(m => agentItem(m, true))}
        </div>)}
        {(city.empty_colonies ?? []).map(e => <div key={'empty:' + e.name} className="ws-team">
          <div className="ws-team-name">{e.name}</div>
          <button className="ws-team-add" title={e.about || 'No agents in it yet'} onClick={() => setModal('colonies')}>
            <span className="grow">Add agents…</span></button>
        </div>)}
        {loners.length > 0 && <div className="ws-team">
          {(colonies.length > 0 || !!city.empty_colonies?.length) && <div className="ws-team-name">Other</div>}
          {loners.map(a => agentItem(a))}
        </div>}
        {city.agents.length === 0 && <p className="hint ws-empty-side">No agents yet.</p>}
      </nav>
      <span className="grow" />
      <nav className="ws-nav ws-foot">
        <button onClick={() => setModal('profile')}>About you and your company</button>
        <button onClick={() => setModal('account')}>Account and AI models</button>
        <button onClick={toTown}>Switch to town view</button>
        <button onClick={async () => {
          try { await api.logout() } catch (e) { setNotice({ ok: false, text: `Couldn't sign out: ${msg(e)}` }); return }
          forgetCredentials(); setWelcome(null); reload()
        }}>Sign out <span className="hint">@{me.username}</span></button>
      </nav>
    </aside>
    <div className="ws-scrim" onClick={() => setNavOpen(false)} />

    <main className={`ws-main${page.kind === 'agent' && page.tab === 'chat' ? ' fill' : ''}`}>
      {noAi && page.kind !== 'home' && <div className="ws-banner">No AI account connected. Agents can't run until you connect Claude or ChatGPT.
        <button className="primary" onClick={connectAi}>Connect AI account</button></div>}

      {page.kind === 'home' && <>
        <Head title="Home" onMenu={() => setNavOpen(true)} />
        <TodayView city={city} hasAi={creds === null ? null : creds.length > 0} onConnectAi={connectAi} onGetStarted={() => setWelcome(true)}
          onChat={id => openAgent(id)} onTown={reload} />
      </>}

      {page.kind === 'agents' && <>
        <Head title="Agents" onMenu={() => setNavOpen(true)}>
          <button onClick={() => setModal('colonies')}>Teams</button>
          <button className="primary" onClick={() => setModal('add')}>Add agents</button>
        </Head>
        <div className="ws-body wide">
          {city.agents.length === 0 ? <Empty onStart={() => setWelcome(true)} onAdd={() => setModal('add')} /> :
          <table className="ws-table">
            <thead><tr><th>Agent</th><th>Team</th><th>Apps</th><th>Model</th><th>Status</th></tr></thead>
            <tbody>{city.agents.map(a => {
              const apps = city.connections.filter(c => a.grants.some(g => g.connection_id === c.id)).map(c => c.name)
              const lead = coloniesOf(city.agents).leadOf.get(a.id)
              return <tr key={a.id} onClick={() => openAgent(a.id)}>
                <td><div className="ws-cell-agent"><Avatar a={a} size={28} /><div className="ellipsis">
                  <a className="ws-rowlink" href={toUrl({ kind: 'agent', id: a.id, tab: 'chat' })} onClick={e => { e.preventDefault(); e.stopPropagation(); openAgent(a.id) }}><b>{nice(a.name)}</b></a>
                  <div className="hint ellipsis">{a.description}</div></div></div></td>
                <td>{leads(a) ? colonyName(a) + ' (lead)' : lead ? colonyName(lead) : <span className="hint">None</span>}</td>
                <td>{apps.length ? apps.join(', ') : <span className="hint">None</span>}</td>
                <td className="mono">{a.brain?.model || a.model || <span className="hint">Default</span>}</td>
                <td><Dot s={status(a.id)} /></td>
              </tr>
            })}</tbody>
          </table>}
        </div>
      </>}

      {page.kind === 'agent' && !agent && <><Head title="Agent not found" onMenu={() => setNavOpen(true)} />
        <div className="ws-body"><p className="hint">It may have been deleted. <a href="/work/agents" onClick={e => { e.preventDefault(); go({ kind: 'agents' }) }}>All agents</a></p></div></>}
      {page.kind === 'agent' && agent && <>
        <Head onMenu={() => setNavOpen(true)} title={<><Avatar a={agent} size={28} /><span className="ellipsis">{nice(agent.name)}</span><Dot s={status(agent.id)} /></>}
          sub={agent.description}>
          <button onClick={() => setSetup({ id: agent.id, step: 0 })} title="Its questions for you, and the apps it uses">Set up</button>
        </Head>
        <div className="ws-tabs" role="tablist">{TABS.map(t =>
          <button key={t.key} role="tab" aria-selected={page.tab === t.key} className={page.tab === t.key ? 'on' : ''}
            onClick={() => go({ kind: 'agent', id: agent.id, tab: t.key })}>{t.label}</button>)}</div>
        {page.tab === 'chat'
          ? <div className="ws-chat"><ThreadView key={agent.id} agent={agent} noAi={noAi} onConnectAi={connectAi} /></div>
          : <div className={`ws-body ws-spot-${page.tab}`}><AgentSection key={`${agent.id}:${page.tab}`} spot={page.tab} agent={agent} city={city} creds={creds} reload={reload} plain
            onSetup={() => setSetup({ id: agent.id, step: 0 })} onGone={() => go({ kind: 'agents' })} /></div>}
      </>}

      {page.kind === 'apps' && <>
        <Head title="Apps" sub="Connect an app once, then choose which agents may use it (an agent's Apps tab)." onMenu={() => setNavOpen(true)} />
        <div className="ws-body"><AppList city={city} reload={reload} onAdvanced={() => setModal('tool')} /></div>
      </>}

      {page.kind === 'files' && <>
        <Head title="Shared files" sub="Files every agent reads, such as your profile (about-us.md)." onMenu={() => setNavOpen(true)} />
        <div className="ws-body"><SharedFilesCard files={city.shared_files} reload={reload} onClose={() => go({ kind: 'home' })} onProfile={() => setModal('profile')} /></div>
      </>}
    </main>

    {notice && <div className={`ws-notice ${notice.ok ? 'ok' : 'bad'}`} role="status">{notice.text}
      <button className="x" onClick={() => setNotice(null)} aria-label="Dismiss">×</button></div>}

    {setupAgent && !modal && <SetupModal key={`${setupAgent.id}:${setup!.step}`} initialStep={setup!.step} agent={setupAgent} city={city} reload={reload}
      onClose={() => setSetup(null)} onChat={() => { setSetup(null); openAgent(setupAgent.id) }}
      onAccount={() => { setSetup({ id: setupAgent.id, step: 2 }); connectAi() }} onAdvanced={() => setModal('tool')} onProfile={() => setModal('profile')} />}
    {welcome && !modal && !setup && <WelcomeModal city={city} reload={reload} onClose={() => setWelcome(false)}
      onAdd={() => { setWelcome(false); setModal('add') }} onStart={startWith} />}
    {modal === 'ai' && <ConnectAiModal onClose={() => setModal(null)} onDone={() => { setModal(null); invalidateCredentials() }} />}
    {modal === 'profile' && <ProfileModal city={city} reload={reload} onClose={() => setModal(null)} />}
    {modal === 'colonies' && <ColoniesModal city={city} reload={reload} onClose={() => setModal(null)}
      onVisit={id => { setModal(null); openAgent(id) }} onAddAgents={() => setModal('add')} />}
    {modal === 'account' && <AccountModal me={me} onClose={() => { setModal(null); invalidateCredentials(); reload() }}
      onDeleted={() => { setModal(null); setSetup(null); setWelcome(null); forgetCredentials(); reload() }} />}
    {modal === 'add' && <AddModal onClose={() => setModal(null)} onWrite={() => setModal('agent')}
      onDone={async id => { setModal(null); await reload(); if (id) { openAgent(id); setSetup({ id, step: 0 }) } }} />}
    {modal === 'agent' && <NewAgentModal onClose={() => setModal(null)}
      onDone={async id => { setModal(null); await reload(); openAgent(id); setSetup({ id, step: 0 }) }} />}
    {modal === 'tool' && <NewToolModal onClose={() => setModal(null)} onDone={async () => { setModal(null); await reload() }} />}
  </div>
}

function Head({ title, sub, onMenu, children }: { title: ReactNode; sub?: string; onMenu: () => void; children?: ReactNode }) {
  return <header className="ws-head">
    <button className="ws-icon ws-menu" onClick={onMenu} aria-label="Menu">≡</button>
    <div className="grow"><h1>{title}</h1>{sub && <p className="hint ellipsis">{sub}</p>}</div>
    {children}
  </header>
}

function Empty({ onStart, onAdd }: { onStart: () => void; onAdd: () => void }) {
  return <div className="ws-emptybox">
    <b>No agents yet</b>
    <p className="hint">Start with a ready-made set (an assistant for your inbox and calendar, and a company team), or pick agents from the market.</p>
    <div className="row center"><button className="primary" onClick={onStart}>Start with the ready-made set</button><button onClick={onAdd}>Browse agents</button></div>
  </div>
}

/** An agent's initial on its colour: who's who at a glance, without a cartoon */
function Avatar({ a, size }: { a: Pick<MyAgent, 'name' | 'color'>; size: number }) {
  return <span className="ws-avatar" style={{ width: size, height: size, background: a.color || '#71717a', fontSize: size * .5 }}
    aria-hidden="true">{nice(a.name).charAt(0).toUpperCase()}</span>
}

function Dot({ s, quiet }: { s: RunStatus | null; quiet?: boolean }) {
  const k = s ?? 'stopped'
  if (quiet && k === 'stopped') return null
  return <span className={`ws-status ${k}`} title={STATUS[k]}><i />{!quiet && STATUS[k]}</span>
}
