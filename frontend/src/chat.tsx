// Talking to an agent, like talking to someone in an RPG: a dialogue box with its portrait, its words
// typed out, and what it's doing in plain words. Opening it starts nothing: it picks up a chat that's
// already running, and otherwise the agent's sandbox starts with your first message.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Access, type Spot } from './access'
import { api, type City, type MailSaid, type MyAgent, type Run, type RunEvent, type RunStatus } from './api'
import { RUN_STATUS_PLAIN, RUN_STATUS_TOWN } from './labels'
import { usePlain } from './look'
import { MailCard } from './mail'
import { MailNote } from './mailbox'
import { Avatar } from './avatar'
import { nice } from './colony'
import { Err, Md, msg } from './ui'
import { POLL, STARTING_SLOW_MS, reduceMotion } from './ui-constants'

/** "mcp__gmail__search_emails" → "gmail" (the app whose stall gets a courier); built-in tools → null */
function toolServer(name: string): string | null {
  return /^mcp__([^_]+(?:_[^_]+)*?)__/.exec(name)?.[1] ?? null
}

/** Its own questions (`ask:` in AGENT.md) while nobody has answered them: its first chat gets to know
 * you, in conversation (backend/app/manifest.py interview), and it writes what it learns to about-me.md. */
export function interviewDue(agent: MyAgent): boolean {
  if (agent.files.some(f => f.path === 'about-me.md')) return false
  const head = /^---\s*\n([\s\S]*?)\n---/.exec(agent.files.find(f => f.path === 'AGENT.md')?.content ?? '')?.[1] ?? ''
  return /^ask:\s*\S/m.test(head)
}

/** Been "starting" for longer than a sandbox normally takes? */
export const startingTooLong = (run: Run | null) =>
  !!run && run.status === 'starting' && !run.ended_at && Date.now() - Date.parse(run.created_at) > STARTING_SLOW_MS

export function Dialogue({ agent, city, hasModel, onStatus, onTool, onTown, onHouse, onSetup, onConnectAi, onClose }: {
  agent: MyAgent; city: City; hasModel: boolean; onStatus?: (s: RunStatus | null) => void; onTool?: (server: string) => void
  onTown?: () => void      // an agent or colony it proposed was added: draw the town again
  onHouse: (spot?: Spot) => void; onSetup: () => void; onConnectAi: () => void; onClose: () => void
}) {
  const [peek, setPeek] = useState<string | null>(null)     // one of the "Can use" chips, opened
  const [run, setRun] = useState<Run | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [typing, setTyping] = useState<{ id: number; shown: number } | null>(null)
  const [reading, setReading] = useState<number | null>(null)   // a reply opened in the reader on the right
  const [slow, setSlow] = useState(false)                       // starting for too long
  const closeReader = useCallback(() => setReading(null), [])
  const log = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)
  const cursor = useRef(0)
  const timer = useRef(0)
  const alive = useRef(true)
  const inFlight = useRef(false)
  const quietPolls = useRef(0)            // polls in a row that brought nothing: slow down
  const live = useRef(false)              // past the first load: new words get typed out, couriers sent
  const hooks = useRef({ onTool })        // the parent's callbacks, without restarting the poll when they change
  useEffect(() => { hooks.current = { onTool } })

  // Ask for what's new. Two ticks never overlap, and events already shown are never shown twice, however
  // the timers and a Send happen to interleave. While the agent is awake but quiet, the asking slows down.
  const poll = useCallback(async function tick(id: number) {
    clearTimeout(timer.current)
    if (inFlight.current) return
    if (document.visibilityState === 'hidden') { timer.current = window.setTimeout(() => tick(id), POLL.chatIdle); return }
    inFlight.current = true
    let ended = false, busy = false
    try {
      const r = await api.runEvents(id, cursor.current)
      if (!alive.current) return
      setRun(r.run)
      setSlow(startingTooLong(r.run))
      ended = !!r.run.ended_at; busy = r.run.status !== 'ready'
      quietPolls.current = r.events.length ? 0 : quietPolls.current + 1
      if (r.events.length) {
        cursor.current = Math.max(cursor.current, r.events[r.events.length - 1].id)
        setEvents(prev => { const seen = new Set(prev.map(e => e.id)); return [...prev, ...r.events.filter(e => !seen.has(e.id))] })
        if (r.events.some(e => e.kind === 'notice')) {   // something happened to an email: show its new state
          const all = await api.runEvents(id, 0)
          const fresh = new Map(all.events.filter(e => e.kind === 'approval').map(e => [e.id, e]))
          if (alive.current) setEvents(prev => prev.map(e => fresh.get(e.id) ?? e))
        }
        if (live.current) {
          for (const e of r.events) {
            if (e.kind === 'tool') { const s = toolServer(String(e.data.name ?? '')); if (s) hooks.current.onTool?.(s) }
          }
          const said = [...r.events].reverse().find(e => e.kind === 'text')
          if (said && !reduceMotion()) setTyping({ id: said.id, shown: 0 })
        }
      }
      live.current = true
      setError(null)
    } catch (e) { if (alive.current) setError(msg(e)) } finally { inFlight.current = false }
    if (!alive.current || ended) return
    timer.current = window.setTimeout(() => tick(id), busy || quietPolls.current < 5 ? POLL.chatLive : POLL.chatIdle)
  }, [])

  useEffect(() => {
    alive.current = true
    api.activeRun(agent.id).then(r => { if (r && alive.current) { setRun(r); poll(r.id) } else live.current = true }, e => { if (alive.current) setError(msg(e)) })
    const visible = () => { if (document.visibilityState === 'visible' && run && !run.ended_at) poll(run.id) }
    document.addEventListener('visibilitychange', visible)
    return () => { alive.current = false; clearTimeout(timer.current); document.removeEventListener('visibilitychange', visible) }
  }, [agent.id, poll]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { onStatus?.(run && !run.ended_at ? run.status : null) }, [run?.status, run?.ended_at]) // eslint-disable-line react-hooks/exhaustive-deps

  // type the newest reply out, a few letters at a time (a click shows it all at once)
  useEffect(() => {
    if (!typing) return
    const full = String(events.find(e => e.id === typing.id)?.data.text ?? '')
    if (typing.shown >= full.length) return
    const t = window.setTimeout(() => setTyping({ id: typing.id, shown: Math.min(full.length, typing.shown + 3) }), 16)
    return () => clearTimeout(t)
  }, [typing, events])
  const finishTyping = () => setTyping(t => t && { ...t, shown: Infinity })

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }) }, [events.length, typing?.shown, run?.status])

  // the box grows with what you type (up to its CSS max-height, then it scrolls), and shrinks back after sending
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`
  }, [text])

  async function send(e: React.FormEvent) {
    e.preventDefault()
    say(text.trim())
  }

  async function say(t: string) {
    if (!t || sending) return
    setSending(true); setError(null)
    try {
      let r = run
      if (!r || r.ended_at) {                // first message, or it went back to sleep: wake it up
        r = await api.startRun(agent.id)
        cursor.current = 0
        setEvents([]); setRun(r); setSlow(false)
      }
      await api.sendMessage(r.id, t)
      setText('')
      poll(r.id)
    } catch (err) { setError(msg(err)) } finally { setSending(false) }
  }

  async function decide(e: RunEvent, sendIt: boolean) {
    setError(null)
    try {
      const done = await api.decideEmail(run!.id, e.id, sendIt)
      setEvents(prev => prev.map(x => x.id === done.id ? done : x))
      if (done.data.state === 'sent' && (done.data.type === 'agent' || done.data.type === 'colony')) onTown?.()
      if (!run!.ended_at) poll(run!.id)
    } catch (err) { setError(msg(err)) }
  }

  async function endChat() {
    clearTimeout(timer.current)
    try { setRun(await api.stopRun(run!.id)); setSlow(false) } catch (err) { setError(msg(err)) }
  }

  const awake = run && !run.ended_at
  const typed = typing && events.find(e => e.id === typing.id)
  const doneTyping = !typed || typing!.shown >= String(typed.data.text ?? '').length
  const read = reading !== null && events.find(e => e.id === reading)
  const plain = usePlain()          // the Office: a work tool's words, a face, no house
  const state = awake ? (plain ? RUN_STATUS_PLAIN : RUN_STATUS_TOWN)[run!.status] : !hasModel ? 'needs an AI' : plain ? 'Idle' : 'asleep'
  return (<>
    {read && <Reader title={`${agent.name} said`} text={String(read.data.text ?? '')} onClose={closeReader} />}
    <div className="dialogue" role="dialog" aria-label={`Talking to ${agent.name}`}>
      <div className="dlg-side">
        <Avatar agent={agent} size={plain ? 44 : 72} asleep={!awake} />
        {plain ? <div className="dlg-who"><div className="dlg-name">{nice(agent.name)}</div><div className="dlg-desc">{agent.description}</div></div>
          : <div className="dlg-name">{agent.name}</div>}
        <div className={`dlg-state ${run?.status ?? 'stopped'}`}>{state}</div>
        <button className="x" onClick={onClose} aria-label="Close chat" title="Close">×</button>
      </div>
      <div className="dlg-main">
        <Access agent={agent} city={city} open={peek} setOpen={setPeek} onChange={spot => onHouse(spot)} />
        <div className="dlg-log" ref={log} hidden={!!peek}>
          {!events.some(e => e.kind === 'user' || e.kind === 'text') && <p className="dlg-line agent">Hi, I'm {/^[a-z]+$/.test(agent.name) ? agent.name[0].toUpperCase() + agent.name.slice(1) : agent.name}. {agent.description || 'What can I do for you?'}</p>}
          {hasModel && !run && !events.length && interviewDue(agent) && <p className="dlg-line agent">
            Before we start, I'd like to get to know you a little, so I'm useful from day one. A few minutes, and you can skip anything.
            <button className="primary dlg-connect" disabled={sending} onClick={() => say("Hi! Let's get to know each other first.")}>Get to know me</button></p>}
          {!hasModel && <p className="dlg-line agent">Before we start, I need an AI to think with. You connect it once, for all of us.
            <button className="primary dlg-connect" onClick={onConnectAi}>Connect your AI (2 minutes)</button></p>}
          {events.map(e => {
            const s = (k: string) => String(e.data[k] ?? '')
            switch (e.kind) {
              case 'user': return <p key={e.id} className="dlg-line you">{!plain && <b>You: </b>}{s('text')}</p>
              case 'text': {
                const full = s('text'), mine = typing?.id === e.id, shown = mine ? full.slice(0, typing.shown) : full
                return <div key={e.id} className="dlg-line agent" onClick={mine && !doneTyping ? finishTyping : undefined} title={mine && !doneTyping ? 'Click to show it all' : undefined}>
                  <button className="dlg-expand" onClick={() => setReading(e.id)} title="Read this in a bigger view" aria-label="Expand reply">⤢</button>
                  <Md text={shown} />{mine && doneTyping && <span className="dlg-more">▼</span>}</div>
              }
              case 'approval': return <MailCard key={e.id} e={e} who={agent.name} className="dlg-mail" onDecide={sendIt => decide(e, sendIt)} />
              case 'mail': return <MailNote key={e.id} said={(e.data.said ?? []) as MailSaid[]} className="dlg-line mail" />
              case 'notice': return null
              case 'error': return <p key={e.id} className="err">{s('detail')}</p>
              case 'status': return s('status') === 'stopped' || s('status') === 'error' ? <p key={e.id} className="dlg-act">{s('detail') || s('status')}</p> : null
              default: return null
            }
          })}
          {run?.status === 'starting' && !slow && <p className="dlg-act">{agent.name} is waking up…</p>}
          {run?.status === 'starting' && slow && <div className="dlg-act slow">
            <p>This is taking longer than usual. Its sandbox may not be starting, or the AI account may have been rejected
              (check it in Settings → Account and AI models).</p>
            <button onClick={endChat}>End chat and try again</button>
          </div>}
          {run?.status === 'busy' && <p className="dlg-act typing">{agent.name} is working<span>.</span><span>.</span><span>.</span></p>}
        </div>
        <Err error={error} />
        <form className="dlg-input" onSubmit={send}>
          <textarea id="dlg-text" ref={box} value={text} rows={1} placeholder={hasModel ? `Say something to ${agent.name}…` : 'Connect your AI first (the button above)'}
            disabled={!hasModel} onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(e) } }} />
          <button className="primary" disabled={!hasModel || !text.trim() || sending}>{plain ? 'Send' : 'Say'}</button>
        </form>
        <div className="dlg-actions">
          <button onClick={() => onHouse()}>{plain ? 'Details' : 'Enter house'}</button>
          <button onClick={onSetup}>Make it your own</button>
          {awake && <button onClick={endChat} title="Let it go back to sleep now (it also sleeps by itself when idle)">End chat</button>}
          <span className="grow" />
          <button onClick={onClose}>{plain ? 'Close' : 'Leave'}</button>
        </div>
      </div>
    </div>
  </>)
}

/** A long reply, opened on the right at full height; it can widen to the whole screen. Esc closes just this. */
function Reader({ title, text, onClose }: { title: string; text: string; onClose: () => void }) {
  const [full, setFull] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.focus()                  // so arrow keys / Page Down scroll the reader, not walk around town
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest?.('input, textarea')) return
      e.stopPropagation()                 // keep keys away from the town (and Esc from closing the chat too)
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', k, true)
    return () => window.removeEventListener('keydown', k, true)
  }, [onClose])
  return (
    <aside className={`reader${full ? ' full' : ''}`} role="dialog" aria-label={title}>
      <div className="reader-head">
        <h2>{title}</h2>
        <button onClick={() => setFull(f => !f)} title={full ? 'Back to the side' : 'Fill the screen'}>{full ? 'Shrink' : 'Full screen'}</button>
        <button onClick={onClose} title="Close (Esc)">Close</button>
      </div>
      <div className="reader-body" ref={box} tabIndex={-1}><Md text={text} /></div>
    </aside>
  )
}
