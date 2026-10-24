// Today: the home page. Not where your agents live (that's the town) but what they did for you:
// what's waiting on you, what your colonies wrote to each other (mailbox.tsx), the reports your
// routines left, and what runs next. Plain and scannable, so a morning check takes a minute.

import { useTeamWord } from './look'
import { useCallback, useState } from 'react'
import { api, type City, type Loop, type Mail, type Mailbox, type Routine, type RoutineIn, type RoutineResult, type RunEvent, type Today } from './api'
import { startingTooLong } from './chat'
import { nice } from './colony'
import { usePoll } from './hooks'
import { MailCard } from './mail'
import { MailSections } from './mailbox'
import { daysAgo, when } from './time'
import { Err, LinkButton, Md, Modal, msg, safeHref } from './ui'
import { POLL } from './ui-constants'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const myZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' } }
const SUGGEST_FIRST = 2                      // ready-made routines shown before "Show more"

const greeting = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }

export function TodayView({ city, hasAi, onChat, onConnectAi, onGetStarted, onTown }: {
  city: City; hasAi: boolean | null; onChat: (agentId: number) => void; onConnectAi: () => void; onGetStarted: () => void
  onTown?: () => void      // an agent or colony an agent proposed was added: draw the town again
}) {
  const [data, setData] = useState<Today | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Routine | 'new' | null>(null)
  const [moreSuggested, setMoreSuggested] = useState(false)
  const tw = useTeamWord()                                         // colony, or cabin in the Office

  const [box, setBox] = useState<Mailbox | null>(null)
  const load = useCallback(() => Promise.all([api.today(), api.mailbox()])
    .then(([d, b]) => { setData(d); setBox(b); setError(null) }, e => setError(msg(e))), [])
  const running = !!data?.results.some(r => !r.run.ended_at) || !!data?.outgoing.length
  usePoll(load, () => (running ? POLL.todayBusy : POLL.today), [load, running])   // watch closely while something runs

  const act = (p: Promise<unknown>) => p.then(r => {
    const d = (r as RunEvent | undefined)?.data
    if (d?.state === 'sent' && (d.type === 'agent' || d.type === 'colony')) onTown?.()
    return load()
  }, e => setError(msg(e)))
  const next = data?.routines.find(r => r.next_run_at)
  const freshReports = data?.results.filter(r => r.run.ended_at && when(r.run.created_at).startsWith('Today')).length ?? 0

  return (
    <main className="today" tabIndex={-1} onKeyDown={e => e.stopPropagation() /* typing here doesn't walk you around town */}>
      <div className="today-inner">
        <header className="today-head">
          <h2>{greeting()}, @{city.me?.username}</h2>
          {data && <p className="today-sum">
            {data.waiting.length + (box?.inbox.length ?? 0) ? <b>{data.waiting.length + (box?.inbox.length ?? 0)} waiting on you</b> : 'Nothing waiting on you'}
            {' · '}{freshReports ? `${freshReports} report${freshReports > 1 ? 's' : ''} today` : 'no reports yet today'}
            {next && <> · next: {next.name}, {when(next.next_run_at)}</>}
          </p>}
        </header>
        <Err error={error} />

        {hasAi === false && <div className="today-banner">Your agents need an AI to think with before any routine can run.
          <button className="primary" onClick={onConnectAi}>Connect your AI</button></div>}
        {city.agents.length === 0 && <div className="today-banner">You don't have any agents yet.
          <button className="primary" onClick={onGetStarted}>Get started</button></div>}

        {data && data.waiting.length > 0 && <section>
          <h3>Waiting on you</h3>
          {data.waiting.map(w => <Letter key={w.event.id} w={w} act={act} />)}
        </section>}

        {box && <MailSections box={box} act={act} />}

        {data && data.outgoing.length > 0 && <section>
          <h3>Going out soon</h3>
          {data.outgoing.map(w => <Letter key={w.event.id} w={w} act={act} />)}
        </section>}

        {data && <Loops city={city} loops={data.loops} onChat={onChat} onError={setError} />}

        {data && data.results.length > 0 && <section>
          <h3>Reports</h3>
          {data.results.map(r => <Report key={r.run.id} r={r} onChat={() => onChat(r.agent.id)} onStop={() => act(api.stopRun(r.run.id))} />)}
        </section>}

        {data && <section>
          <div className="t-sec-head"><h3>Routines</h3>
            {city.agents.length > 0 && <button onClick={() => setEditing('new')}>+ New routine</button>}</div>
          {data.routines.length === 0 && <p className="hint">A routine is a job an agent does on its own, on a schedule: a morning brief,
            a Friday update. Its report shows up here, and any email it sends waits for your Send unless you gave it rules (its house → Tools).</p>}
          {data.routines.map(r => <div key={r.id} className={`t-routine${r.enabled ? '' : ' off'}`}>
            <div className="grow">
              <div><b>{r.name}</b> <span className="hint">· {nice(r.agent)}</span></div>
              <div className="hint">{r.when} ({r.timezone}){r.enabled ? r.next_run_at && <> · next {when(r.next_run_at)}</> : ' · paused'}
                {r.last_run?.status === 'error' && <span className="t-bad"> · last run failed</span>}</div>
            </div>
            {r.trigger === 'schedule' && <button onClick={() => act(api.runRoutine(r.id))} disabled={!!r.last_run && !r.last_run.ended_at}
              title="Run it now; its schedule stays the same">{r.last_run && !r.last_run.ended_at ? 'Running…' : 'Run now'}</button>}
            <button onClick={() => act(api.updateRoutine(r.id, { enabled: !r.enabled }))}>{r.enabled ? 'Pause' : 'Resume'}</button>
            <button onClick={() => setEditing(r)}>Edit</button>
          </div>)}
          {data.suggested.length > 0 && <div className="t-suggest">
            <div className="hint">Ready-made for your team{hasAi === false ? ' (they run once an AI is connected)' : ''}:</div>
            {(moreSuggested ? data.suggested : data.suggested.slice(0, SUGGEST_FIRST)).map(s => <div key={s.slug + s.name} className="t-routine">
              <div className="grow"><b>{s.name}</b> <span className="hint">· {nice(s.agent)} · {s.trigger === 'email' ? 'when email arrives from someone you\'ve written to' : describe(s.days, s.at)}</span>
                <div className="hint">{s.prompt}</div></div>
              <button className="primary" onClick={() => act(api.addRoutine({ agent_id: s.agent_id, name: s.name, prompt: s.prompt,
                days: s.days, at: s.at, timezone: myZone(), trigger: s.trigger ?? 'schedule' }))}>Add</button>
            </div>)}
            {!moreSuggested && data.suggested.length > SUGGEST_FIRST && <p className="hint">
              <LinkButton onClick={() => setMoreSuggested(true)}>Show {data.suggested.length - SUGGEST_FIRST} more</LinkButton></p>}
          </div>}
        </section>}
        {data && data.sent.length > 0 && <section>
          <h3>Sent, posted and added by your agents</h3>
          {data.sent.map(w => <div key={w.event.id} className="t-sent">
            {w.event.data.type === 'agent' || w.event.data.type === 'colony'
              ? <><Who a={w.agent} /> <span className="grow">added {w.event.data.type === 'agent' ? 'the agent' : `the ${tw.one}`} <b>{String(w.event.data.name)}</b></span></>
              : w.event.data.type === 'post'
              ? <><Who a={w.agent} /> <span className="grow">on LinkedIn: {safeHref(w.event.data.url)
                ? <a href={safeHref(w.event.data.url)} target="_blank" rel="noopener noreferrer"><b>{String(w.event.data.text).slice(0, 80)}</b></a>
                : <b>{String(w.event.data.text).slice(0, 80)}</b>}</span></>
              : <><Who a={w.agent} /> <span className="grow">to {String(w.event.data.to)}: <b>{String(w.event.data.subject || '(no subject)')}</b></span></>}
            <span className="hint">{w.event.data.auto ? 'on its own' : w.event.data.type === 'post' ? 'you pressed Post' : w.event.data.type === 'agent' || w.event.data.type === 'colony' ? 'you pressed Add' : 'you pressed Send'} · {when(String(w.event.data.sent_at || w.event.created_at))}</span>
          </div>)}
        </section>}
      </div>
      {editing && <RoutineModal city={city} routine={editing === 'new' ? null : editing}
        onClose={() => setEditing(null)} onDone={() => { setEditing(null); load() }} />}
    </main>
  )
}

/** An email an agent sent: waiting for your Send, or going out by its rules */
function Letter({ w, act }: { w: Mail; act: (p: Promise<unknown>) => void }) {
  return <MailCard e={w.event} who={<Who a={w.agent} />} className="t-card mail"
    extra={<>{w.routine && <> · from <i>{w.routine}</i></>} · {when(w.event.created_at)}</>}
    onDecide={send => act(api.decideEmail(w.run_id, w.event.id, send))} />
}

/** Does this agent have Gmail (any of its tools)? */
function usesGmail(city: City, agentId: number): boolean {
  const gmail = new Set(city.connections.filter(c => c.app === 'gmail').map(c => c.id))
  return !!city.agents.find(a => a.id === agentId)?.grants.some(g => gmail.has(g.connection_id))
}

/** Email threads waiting on someone, from the email index: the proactive part. One click asks an agent
    with Gmail to draft the replies or follow-ups; they open in its chat, and nothing is sent unasked. */
function Loops({ city, loops, onChat, onError }: {
  city: City; loops: Today['loops']; onChat: (agentId: number) => void; onError: (e: string) => void
}) {
  const helpers = city.agents.filter(a => usesGmail(city, a.id))
  const [pick, setWho] = useState(0)
  const who = helpers.some(a => a.id === pick) ? pick : helpers[0]?.id ?? 0
  const [busy, setBusy] = useState(false)
  if (loops.indexing && !loops.waiting_on_me.length && !loops.gone_quiet.length)
    return <section><h3>Email</h3><p className="hint">Reading who you email, to find threads waiting on you. This takes a few minutes the first time.</p></section>
  if (!loops.waiting_on_me.length && !loops.gone_quiet.length) return null

  async function ask(kind: 'reply' | 'follow') {
    const list = (kind === 'reply' ? loops.waiting_on_me : loops.gone_quiet)
      .map(l => `- email_id ${l.email_id}: ${l.with}, "${l.subject}" (${daysAgo(l.days)})`).join('\n')
    const message = kind === 'reply'
      ? `These emails are waiting on my reply. Read each one (read_email), then draft a short reply to each with draft_email, in my voice. Tell me which ones need me to decide something.\n${list}`
      : `I wrote these and nobody answered. Read each thread (read_email), then draft a short, friendly follow-up to each with draft_email. Skip any that don't need one, and say why.\n${list}`
    setBusy(true)
    try { await api.startRun(who, message); onChat(who) } catch (e) { onError(msg(e)) } finally { setBusy(false) }
  }
  const row = (l: Loop) => <div key={l.thread_id} className="t-sent">
    <b>{l.with}</b> <span className="grow">{l.subject || '(no subject)'}</span><span className="hint">{daysAgo(l.days)}</span></div>
  const button = (kind: 'reply' | 'follow', label: string) => helpers.length > 0
    && <button className="tiny" disabled={busy} onClick={() => ask(kind)}>{label}</button>
  return <section>
    {loops.waiting_on_me.length > 0 && <>
      <div className="t-sec-head"><h3>Email waiting on you</h3>{button('reply', 'Draft replies')}</div>
      {loops.waiting_on_me.map(row)}</>}
    {loops.gone_quiet.length > 0 && <>
      <div className="t-sec-head"><h3>Gone quiet</h3>{button('follow', 'Draft follow-ups')}</div>
      {loops.gone_quiet.map(row)}</>}
    {helpers.length > 1 && <p className="hint">Drafted by <select value={who} onChange={e => setWho(Number(e.target.value))}>
      {helpers.map(a => <option key={a.id} value={a.id}>{nice(a.name)}</option>)}</select></p>}
    {helpers.length === 0 && <p className="hint">Give an agent Gmail (its house → Tools) and it can draft these for you.</p>}
  </section>
}

function Who({ a }: { a: { name: string; color: string } }) {
  return <span className="t-who"><span className="sw" style={{ background: a.color }} />{nice(a.name)}</span>
}

function describe(days: string, at: string): string {
  const d = [...days].sort().join('')
  const name = ({ '0123456': 'Every day', '01234': 'Weekdays', '56': 'Weekends' } as Record<string, string>)[d]
    ?? [...d].map(x => DAYS[Number(x)]).join(', ')
  return `${name} at ${at}`
}

/** One routine run: its report first, and on request exactly what it did to get there. */
function Report({ r, onChat, onStop }: { r: RoutineResult; onChat: () => void; onStop: () => void }) {
  const [open, setOpen] = useState(false)
  const [steps, setSteps] = useState(false)
  const live = !r.run.ended_at, failed = r.run.status === 'error' || r.done.ok === false
  const slow = startingTooLong(r.run)
  const long = r.report.split('\n').length > 10 || r.report.length > 700
  const did = r.steps.map(s => s.count > 1 ? `${s.tool} ×${s.count}` : s.tool)
  const secs = r.done.duration_ms ? Math.round(r.done.duration_ms / 1000) : null
  return (
    <div className={`t-card${failed ? ' failed' : ''}`}>
      <div className="t-meta">
        <b className="t-title">{r.routine}</b> · <Who a={r.agent} /> · {when(r.run.created_at)}
        <span className={`t-state ${live ? 'live' : failed ? 'bad' : 'ok'}`}>{live ? (r.run.status === 'starting' ? 'starting' : 'working') : failed ? 'failed' : 'done'}</span>
      </div>
      {failed && <p className="t-bad">{r.run.detail && r.run.detail !== 'Finished' ? r.run.detail : r.errors[r.errors.length - 1] || 'It stopped before finishing.'}</p>}
      {live && !slow && <p className="hint">{r.run.status === 'starting' ? 'Starting its sandbox…' : did.length ? `So far: ${did.slice(-4).join(' → ')}` : 'Thinking…'}</p>}
      {slow && <p className="t-bad">This is taking longer than usual. Its sandbox may not be starting, or the AI account may have been rejected
        (check it in Settings → Account and AI models). <button className="tiny" onClick={onStop}>Stop it and try again</button></p>}
      {r.report && <div className={`t-report${long && !open ? ' clipped' : ''}`}><Md text={r.report} /></div>}
      <div className="row tight">
        {long && <button className="tiny" onClick={() => setOpen(!open)}>{open ? 'Show less' : 'Read all'}</button>}
        {!live && (r.steps.length > 0 || secs) && <button className="tiny" onClick={() => setSteps(!steps)}>{steps ? 'Hide' : 'What it did'}</button>}
        <button className="tiny" onClick={onChat}>Ask {nice(r.agent.name)} about it</button>
      </div>
      {steps && <div className="t-steps">
        {did.length ? <ol>{did.map((d, i) => <li key={i}>{d}</li>)}</ol> : <p className="hint">It answered without using any apps.</p>}
        <p className="hint">{secs !== null && `Took ${secs < 90 ? `${secs}s` : `${Math.round(secs / 60)} min`}`}
          {r.done.cost_usd != null && ` · about $${r.done.cost_usd.toFixed(2)} on your AI account`}</p>
      </div>}
    </div>
  )
}

function RoutineModal({ city, routine, onClose, onDone }: { city: City; routine: Routine | null; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState<Required<RoutineIn>>(() => routine
    ? { agent_id: routine.agent_id, name: routine.name, prompt: routine.prompt, days: routine.days, at: routine.at, timezone: routine.timezone, enabled: routine.enabled, trigger: routine.trigger }
    : { agent_id: city.agents[0]?.id ?? 0, name: '', prompt: '', days: '01234', at: '08:00', timezone: myZone(), enabled: true, trigger: 'schedule' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (patch: Partial<RoutineIn>) => setF({ ...f, ...patch })
  const emailAgent = usesGmail(city, f.agent_id)
  const toggleDay = (d: string) => set({ days: f.days.includes(d) ? f.days.replace(d, '') : [...f.days + d].sort().join('') })

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try { await (routine ? api.updateRoutine(routine.id, f) : api.addRoutine(f)); onDone() }
    catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }
  async function remove() {
    if (!routine || !confirm(`Delete "${routine.name}"? Its past reports stay.`)) return
    try { await api.deleteRoutine(routine.id); onDone() } catch (err) { setError(msg(err)) }
  }
  return (
    <Modal title={routine ? `Edit ${routine.name}` : 'New routine'} onClose={onClose}>
      <form className="form" onSubmit={save}>
        <label>Name<input value={f.name} onChange={e => set({ name: e.target.value })} placeholder="Morning brief" required /></label>
        <label>Who does it
          <select value={f.agent_id} onChange={e => set({ agent_id: Number(e.target.value) })}>
            {city.agents.map(a => <option key={a.id} value={a.id}>{nice(a.name)}</option>)}
          </select></label>
        <label>What to do <span className="hint">Write it like a message to them. Their report lands on Today.</span>
          <textarea className="t-prompt" rows={5} value={f.prompt} onChange={e => set({ prompt: e.target.value })} required
            placeholder="Go through my inbox and calendar. Tell me the three things only I can do today, and draft replies to anything urgent." /></label>
        <div><div className="label">When</div>
          <div className="seg">
            <button type="button" className={f.trigger === 'schedule' ? 'on' : ''} onClick={() => set({ trigger: 'schedule' })}>On a schedule</button>
            <button type="button" className={f.trigger === 'email' ? 'on' : ''} onClick={() => set({ trigger: 'email' })}>When email arrives</button>
          </div></div>
        {f.trigger === 'email' ? <p className="hint">It runs when an email arrives from someone you've written to (checked every couple of
          minutes, at most 20 times a day), and it's told which emails are new. Strangers, newsletters and no-reply senders
          don't start it. {!emailAgent && <b>{nice(city.agents.find(a => a.id === f.agent_id)?.name ?? 'This agent')} needs Gmail first (its house → Tools).</b>}</p>
        : <><div className="form-row">
          <div><div className="label">Days</div>
            <div className="seg">{DAYS.map((d, i) => <button type="button" key={d} className={f.days.includes(String(i)) ? 'on' : ''}
              onClick={() => toggleDay(String(i))}>{d[0]}</button>)}</div></div>
          <label>Time<input type="time" value={f.at} onChange={e => set({ at: e.target.value })} required /></label>
        </div>
        <p className="hint">Times are in {f.timezone}.{f.timezone !== myZone() && <> <LinkButton onClick={() => set({ timezone: myZone() })}>Use {myZone()}</LinkButton></>}</p>
        </>}
        <Err error={error} />
        <div className="row">
          <button className="primary" disabled={busy || !f.days || !f.agent_id}>{routine ? 'Save' : 'Add routine'}</button>
          <button type="button" onClick={onClose}>Cancel</button>
          <span className="grow" />
          {routine && <button type="button" className="danger" onClick={remove}>Delete</button>}
        </div>
      </form>
    </Modal>
  )
}
