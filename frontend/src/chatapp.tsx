// The chat app: Agent Town as a messaging app, for a phone's home screen (/chat). Each agent is a
// conversation that carries on across its chats and routines; emails waiting on you show inline and
// on the Waiting screen; notifications arrive through the service worker (public/sw.js) when the
// app is closed. The town itself is one tap away, but nothing here needs it.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type City, type Conversation, type MailSaid, type MyAgent, type RunEvent, type Thread, type Today } from './api'
import { startingTooLong } from './chat'
import { coloniesOf, colonyName, nice } from './colony'
import { ConnectAiModal } from './connect-ai'
import { useCredentials, usePoll, useUnauthenticated } from './hooks'
import { MailCard } from './mail'
import { MailNote } from './mailbox'
import { Avatar } from './avatar'
import { LookContext, lookOf, useApplyLook, useTeamWord } from './look'
import { short } from './time'
import { Err, LinkButton, Md, msg } from './ui'
import { POLL } from './ui-constants'
import { preview } from './labels'

type Screen = { kind: 'list' } | { kind: 'thread'; agentId: number } | { kind: 'waiting' }

function fromUrl(): Screen {
  const q = new URLSearchParams(location.search)
  if (q.get('agent')) return { kind: 'thread', agentId: Number(q.get('agent')) }
  if (q.has('today')) return { kind: 'waiting' }
  return { kind: 'list' }
}

function toUrl(s: Screen): string {
  return s.kind === 'thread' ? `/chat?agent=${s.agentId}` : s.kind === 'waiting' ? '/chat?today' : '/chat'
}

export function ChatApp() {
  const [city, setCity] = useState<City | null>(null)
  const [screen, setScreen] = useState<Screen>(fromUrl)
  const [error, setError] = useState<string | null>(null)
  const [connect, setConnect] = useState(false)
  const { creds } = useCredentials()
  const noAi = !!city?.me && creds !== null && creds.length === 0
  const loadCity = useCallback(() => api.city().then(c => { setCity(c); setError(null) }, e => setError(msg(e))), [])
  useEffect(() => { loadCity() }, [loadCity])
  useUnauthenticated(loadCity)                                  // the session expired: back to Sign in
  useEffect(() => {
    const back = () => setScreen(fromUrl())
    window.addEventListener('popstate', back)
    return () => window.removeEventListener('popstate', back)
  }, [])
  const go = (s: Screen) => { history.pushState(null, '', toUrl(s)); setScreen(s) }
  const look = lookOf(city?.map_style)                          // the look you picked in Settings, here too
  useApplyLook(look)

  if (!city) return <div className="ca ca-signin"><Err error={error} />{error && <button className="primary" onClick={loadCity}>Retry</button>}</div>
  if (!city.me) return <SignIn onDone={loadCity} />
  const agent = screen.kind === 'thread' ? city.agents.find(a => a.id === screen.agentId) : undefined
  return <LookContext.Provider value={look}><div className="ca">
    {screen.kind === 'thread' && agent ? <ThreadView agent={agent} noAi={noAi} onConnectAi={() => setConnect(true)} onBack={() => go({ kind: 'list' })} />
      : screen.kind === 'waiting' ? <Waiting onBack={() => go({ kind: 'list' })} onOpen={id => go({ kind: 'thread', agentId: id })} />
      : <List city={city} noAi={noAi} onConnectAi={() => setConnect(true)} onOpen={id => go({ kind: 'thread', agentId: id })} onWaiting={() => go({ kind: 'waiting' })} />}
    {connect && <ConnectAiModal onClose={() => setConnect(false)} onDone={() => setConnect(false)} />}
  </div></LookContext.Provider>
}

function SignIn({ onDone }: { onDone: () => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  return <div className="ca ca-signin">
    <img src="/icon.svg" alt="" width={72} height={72} />
    <h1>Agent Town</h1>
    <form onSubmit={e => { e.preventDefault(); api.login(login, password).then(onDone, err => setError(msg(err))) }}>
      <input placeholder="Email or username" value={login} onChange={e => setLogin(e.target.value)} autoComplete="username" />
      <input placeholder="Password" type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" />
      <button className="primary">Sign in</button>
    </form>
    <Err error={error} />
    <p className="hint">New here? <a href="/">Make your town first</a>.</p>
  </div>
}

function List({ city, noAi, onConnectAi, onOpen, onWaiting }: { city: City; noAi: boolean; onConnectAi: () => void; onOpen: (id: number) => void; onWaiting: () => void }) {
  const [convs, setConvs] = useState<Conversation[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  usePoll(() => api.conversations().then(c => { setConvs(c); setError(null) }, e => setError(msg(e))), () => POLL.conversations, [])
  const waiting = convs?.reduce((n, c) => n + c.waiting, 0) ?? 0
  const conv = new Map((convs ?? []).map(c => [c.agent.id, c]))
  // the same groups as the town's blocks: each colony, its lead first, then the agents with no team
  const { colonies, loners } = coloniesOf(city.agents)
  const tw = useTeamWord()
  const groups: { name: string | null; agents: MyAgent[] }[] = [
    ...colonies.map(c => ({ name: colonyName(c.lead, tw.one), agents: [c.lead, ...c.members] })),
    ...(loners.length ? [{ name: colonies.length ? 'Other' : null, agents: loners }] : []),
  ]
  const row = (a: MyAgent) => {
    const c = conv.get(a.id)
    return <li key={a.id}><button onClick={() => onOpen(a.id)}>
      <Avatar agent={a} size={44} />
      <span className="ca-who">
        <span className="ca-row"><b>{nice(a.name)}</b><span className="grow" />
          <span className="hint">{c?.last ? short(c.last.created_at) : ''}</span></span>
        <span className="ca-row"><span className="ca-prev">{c?.status === 'busy' ? 'working…' : preview(c?.last ?? null, a.description, tw.one)}</span>
          {!!c?.waiting && <span className="ca-badge">{c.waiting}</span>}</span>
      </span>
    </button></li>
  }
  return <>
    <header className="ca-bar">
      <h1>Agent Town</h1><span className="grow" />
      <Bell />
      <a className="button" href="/" title="Your town, with every agent's house">Town</a>
    </header>
    <Install />
    {noAi && <button className="ca-banner" onClick={onConnectAi}>🧠 No AI account connected. Your agents can't answer until you connect Claude or ChatGPT.</button>}
    {waiting > 0 && <button className="ca-banner" onClick={onWaiting}>✉️ {waiting} email{waiting > 1 ? 's' : ''} waiting on you</button>}
    <Err error={error} />
    {city.agents.length === 0 && <p className="ca-empty">No agents yet. <a href="/">Add some in your town</a>.</p>}
    <div className="ca-list">
      {groups.map((g, i) => <section key={g.name ?? i}>
        {g.name && <h3 className="ca-h">{g.name}</h3>}
        <ul className="ca-list">{g.agents.map(row)}</ul>
      </section>)}
    </div>
  </>
}

/** One agent's conversation, across its chats and routines. Without `onBack` it has no header of its own
    (the workspace shows the agent's name and status above it). */
export function ThreadView({ agent, noAi, onConnectAi, onBack }: { agent: MyAgent; noAi?: boolean; onConnectAi?: () => void; onBack?: () => void }) {
  const [t, setT] = useState<Thread | null>(null)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cursor = useRef(0)
  const live = useRef(false)
  const log = useRef<HTMLDivElement>(null)
  const stick = useRef(true)                                   // at the bottom: follow new messages

  const poll = useCallback(async () => {
    const n = await api.thread(agent.id, cursor.current ? { after: cursor.current } : {})
    cursor.current = n.cursor
    setT(prev => {
      if (!prev) return n
      const mail = new Map(n.mail.map(e => [e.id, e]))
      const seen = new Set(prev.messages.map(m => m.id))
      const messages = [...prev.messages, ...n.messages.filter(m => !seen.has(m.id))]
        .map(m => m.kind === 'approval' && mail.has(m.id) ? { ...m, data: mail.get(m.id)!.data } : m)
      return { ...n, messages, more: prev.more }
    })
    live.current = !!n.run && !n.run.ended_at
  }, [agent.id])

  useEffect(() => { cursor.current = 0; live.current = false; setT(null) }, [agent.id])
  usePoll(async () => { try { await poll(); setError(null) } catch (e) { setError(msg(e)) } },
    () => (live.current ? POLL.threadLive : POLL.threadIdle), [poll])

  useEffect(() => { if (stick.current) log.current?.scrollTo({ top: log.current.scrollHeight }) }, [t?.messages.length, t?.run?.status])

  async function older() {
    if (!t?.messages.length) return
    try {
      const o = await api.thread(agent.id, { before: t.messages[0].id })
      const h = log.current?.scrollHeight ?? 0
      setT(prev => {                                           // anything that arrived meanwhile stays
        if (!prev) return prev
        const seen = new Set(prev.messages.map(m => m.id))
        return { ...prev, messages: [...o.messages.filter(m => !seen.has(m.id)), ...prev.messages], more: o.more }
      })
      requestAnimationFrame(() => { if (log.current) log.current.scrollTop += log.current.scrollHeight - h })
    } catch (e) { setError(msg(e)) }
  }

  async function send(e?: React.FormEvent) {
    e?.preventDefault()
    const said = text.trim()
    if (!said || sending) return
    setSending(true); setError(null); stick.current = true
    try { await api.startRun(agent.id, said); setText(''); await poll() } catch (err) { setError(msg(err)) } finally { setSending(false) }
  }

  async function decide(m: RunEvent & { run_id: number }, sendIt: boolean) {
    try {
      const done = await api.decideEmail(m.run_id, m.id, sendIt)
      setT(prev => prev && { ...prev, messages: prev.messages.map(x => x.id === done.id ? { ...x, data: done.data } : x) })
    } catch (err) { setError(msg(err)) }
  }

  async function stop() {
    if (!t?.run) return
    try { await api.stopRun(t.run.id); await poll() } catch (err) { setError(msg(err)) }
  }

  const status = t?.run && !t.run.ended_at ? t.run.status : null
  const slow = startingTooLong(t?.run ?? null)
  const says = status === 'busy' ? 'working…' : status === 'starting' ? 'waking up…' : status ? 'here' : noAi ? 'needs an AI to think with' : 'asleep: your message wakes it'
  return <>
    {onBack && <header className="ca-bar">
      <button className="ca-back" onClick={onBack} aria-label="Back">‹</button>
      <Avatar agent={agent} size={32} />
      <div className="ca-title"><b>{nice(agent.name)}</b>
        <span className="hint">{says}</span></div>
    </header>}
    <div className="ca-log" ref={log} onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80 }}>
      {t?.more && <button className="ca-older" onClick={older}>Earlier messages</button>}
      {noAi && <div className="ca-mail"><b>No AI account connected.</b> {nice(agent.name)} can't answer until you connect Claude or ChatGPT.
        {onConnectAi && <div className="row tight"><button className="primary" onClick={onConnectAi}>Connect your AI</button></div>}</div>}
      {t && t.messages.length === 0 && <p className="ca-empty">{agent.description || `Say something to ${nice(agent.name)}.`}</p>}
      {t?.messages.map(m => m.kind === 'approval'
        ? <MailCard key={m.id} e={m} who={nice(agent.name)} className="ca-mail" onDecide={s => decide(m, s)} />
        : m.kind === 'mail' ? <MailNote key={m.id} said={(m.data.said ?? []) as MailSaid[]} className="ca-msg them mail" />
        : <div key={m.id} className={`ca-msg ${m.kind === 'user' ? 'me' : 'them'}`}>
          {m.routine && <div className="ca-routine">{m.routine}</div>}
          {m.kind === 'user' ? String(m.data.text ?? '') : <Md text={String(m.data.text ?? '')} />}
          <span className="ca-time">{short(m.created_at)}</span>
        </div>)}
      {(status === 'busy' || status === 'starting' || sending) && <div className="ca-msg them typing"><span>.</span><span>.</span><span>.</span></div>}
      {slow && <div className="ca-mail"><b>This is taking longer than usual.</b> Its sandbox may not be starting, or the AI account may have been
        rejected (check it under Account → AI accounts). <div className="row tight"><button onClick={stop}>End chat and try again</button></div></div>}
    </div>
    <Err error={error} />
    <form className="ca-input" onSubmit={send}>
      <textarea rows={1} value={text} placeholder={`Message ${nice(agent.name)}`} onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !('ontouchstart' in window)) { e.preventDefault(); send() } }} />
      <button className="primary" disabled={!text.trim() || sending} aria-label="Send">↑</button>
    </form>
  </>
}

/** Emails waiting for your Send, and those going out by an agent's rules: the same cards as Today */
function Waiting({ onBack, onOpen }: { onBack: () => void; onOpen: (agentId: number) => void }) {
  const [d, setD] = useState<Today | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => api.today().then(x => { setD(x); setError(null) }, e => setError(msg(e))), [])
  usePoll(load, () => POLL.waiting, [load])
  const mail = [...(d?.waiting ?? []), ...(d?.outgoing ?? [])]
  return <>
    <header className="ca-bar">
      <button className="ca-back" onClick={onBack} aria-label="Back">‹</button>
      <div className="ca-title"><b>Waiting on you</b></div>
    </header>
    <div className="ca-log">
      <Err error={error} />
      {d && mail.length === 0 && <p className="ca-empty">Nothing waiting on you.</p>}
      {mail.map(w => <MailCard key={w.event.id} e={w.event} who={<LinkButton onClick={() => onOpen(w.agent.id)}>{nice(w.agent.name)}</LinkButton>}
        className="ca-mail" extra={w.routine ? <> · from <i>{w.routine}</i></> : null}
        onDecide={s => api.decideEmail(w.run_id, w.event.id, s).then(load, e => setError(msg(e)))} />)}
      {d && d.loops.waiting_on_me.length > 0 && <>
        <h3 className="ca-h">Email waiting on your reply</h3>
        {d.loops.waiting_on_me.map(l => <div key={l.thread_id} className="ca-loop"><b>{l.with}</b> {l.subject} <span className="hint">{l.days ? `${l.days}d` : 'today'}</span></div>)}
        <p className="hint">Ask an agent with Gmail to draft these, or use Today in your town.</p>
      </>}
    </div>
  </>
}

const b64 = (s: string) => Uint8Array.from(atob((s + '='.repeat((4 - s.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
const standalone = () => matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
const ios = () => /iPhone|iPad|iPod/.test(navigator.userAgent)

/** Notifications on this device: on, off, or why not */
function Bell() {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  const [on, setOn] = useState<boolean | null>(supported ? null : false)
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  useEffect(() => {
    if (!supported) return
    navigator.serviceWorker.ready.then(r => r.pushManager.getSubscription()).then(s => setOn(!!s), () => setOn(false))
  }, [supported])

  async function turnOn() {
    setNote(null)
    try {
      if (await Notification.requestPermission() !== 'granted') { setNote('Notifications are blocked for this site: allow them in your browser settings.'); return }
      const reg = await navigator.serviceWorker.ready
      const { key } = await api.pushKey()
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(key) })
      await api.subscribePush(sub.toJSON())
      setOn(true)
    } catch (e) { setNote(msg(e)) }
  }
  async function turnOff() {
    setNote(null)
    try {
      const sub = await (await navigator.serviceWorker.ready).pushManager.getSubscription()
      if (sub) { await api.unsubscribePush(sub.endpoint).catch(() => {}); await sub.unsubscribe() }
      setOn(false)
    } catch (e) { setNote(msg(e)) }
  }

  return <>
    <button onClick={() => setOpen(!open)} title="Notifications" aria-label="Notifications" aria-expanded={open}>{on ? '🔔' : '🔕'}</button>
    {open && <div className="ca-pop">
      {!supported ? <p>{ios() && !standalone()
        ? <>On iPhone, notifications work once Agent Town is on your Home Screen: tap Share, then <b>Add to Home Screen</b>, and open it from there.</>
        : 'This browser can\'t show notifications.'}</p>
        : on ? <>
          <p>This device gets a notification when an email waits for your Send, a routine finishes, or an agent answers while you're away.</p>
          <div className="row tight"><button onClick={() => api.testPush().then(() => setNote('Sent: it should arrive in a moment.'), e => setNote(msg(e)))}>Send a test</button>
            <button onClick={turnOff}>Turn off</button></div>
        </> : <>
          <p>Get a notification when an email waits for your Send, a routine finishes, or an agent answers while you're away.
            It says who and what, never an email's text.</p>
          <button className="primary" onClick={turnOn}>Turn on notifications</button>
        </>}
      {note && <p className="hint">{note}</p>}
    </div>}
  </>
}

type InstallEvent = Event & { prompt: () => Promise<void> }

/** "Install the app": Chrome and Android offer it through an event; iPhone only by Share → Add to Home Screen */
function Install() {
  const [ev, setEv] = useState<InstallEvent | null>(null)
  const [hidden, setHidden] = useState(() => { try { return standalone() || localStorage.getItem('agenttown.install') === 'no' } catch { return true } })
  useEffect(() => {
    const h = (e: Event) => { e.preventDefault(); setEv(e as InstallEvent) }
    window.addEventListener('beforeinstallprompt', h)
    return () => window.removeEventListener('beforeinstallprompt', h)
  }, [])
  if (hidden || (!ev && !ios())) return null
  const no = () => { setHidden(true); try { localStorage.setItem('agenttown.install', 'no') } catch { /* private mode */ } }
  return <div className="ca-install">
    {ev ? <><span>Put Agent Town on your home screen, like any app.</span>
      <button className="primary" onClick={() => ev.prompt().then(() => setHidden(true), () => {})}>Install</button></>
      : <span>Put Agent Town on your Home Screen: tap Share, then <b>Add to Home Screen</b>.</span>}
    <button onClick={no} aria-label="Not now">✕</button>
  </div>
}
