// Mail on Today (backend/app/mail.py): what your colonies ask you, what they've written to each other,
// and what waits for the mayor's next look. On the map: a colony's post office (PostOfficeCard), and
// its lead when it comes to the square to see you (VisitModal). Answering a question sends your answer back to whoever
// asked, as mail. A thread that hit its limit (too long, too costly, two agents going back and forth)
// pauses here until you say whether it goes on.

import { useTeamWord } from './look'
import { useCallback, useEffect, useState } from 'react'
import { api, type Letter, type Mailbox, type MailSaid, type MailThreadInfo, type MailWho } from './api'
import { nice } from './colony'
import { when } from './time'
import { Err, LinkButton, Md, Modal, msg } from './ui'

const STATUS = { open: 'going', paused: 'paused', done: 'done' } as const

function Who({ a }: { a: MailWho | null }) {
  if (!a) return <span className="t-who">you</span>
  return <span className="t-who"><span className="sw" style={{ background: a.color }} />{nice(a.name)}</span>
}

/** The Mail sections of Today. act: run a request, then load Today and the mailbox again. */
export function MailSections({ box, act }: { box: Mailbox; act: (p: Promise<unknown>) => void }) {
  const [thread, setThread] = useState<number | null>(null)
  const [writing, setWriting] = useState(false)
  const between = box.threads.filter(t => t.agents.length > 1)      // not one agent's note to you
  const live = between.filter(t => t.status !== 'done')
  const forMayor = box.waiting.filter(l => l.state === 'waiting'), queued = box.waiting.filter(l => l.state === 'queued')
  const w = useTeamWord()
  return <>
    {box.inbox.length > 0 && <section>
      <h3>Your {w.many} ask you</h3>
      {box.inbox.map(l => <Note key={l.id} l={l} act={act} onThread={() => setThread(l.thread_id)} />)}
    </section>}

    <section>
      <div className="t-sec-head"><h3>Between your {w.many}</h3>
        {box.colonies.length > 0 && <button onClick={() => setWriting(true)}>Write to a {w.one}</button>}</div>
      {!between.length && <p className="hint">Your {w.many} can write to each other: your assistant asks Research, Research
        answers. {box.mayor ? <>{nice(box.mayor.name)}, your mayor, looks at new requests every 30 minutes and wakes the {w.many}
        worth working on now.</> : <>Add the mayor from the market to have new requests wait for a look before anyone is woken.</>}</p>}
      {forMayor.length > 0 && <Waiting title={`Waiting for ${box.mayor ? nice(box.mayor.name) : 'a look'}`}
        note={box.mayor_checked_at ? `last look ${when(box.mayor_checked_at)}` : ''} mail={forMayor} onThread={setThread}
        send={l => act(api.deliverMail(l.id))} />}
      {queued.length > 0 && <Waiting title="About to go" mail={queued} onThread={setThread}
        note="each goes once its colony can start: a few run at once, and every one needs your AI connected" />}
      {live.map(t => <ThreadRow key={t.id} t={t} onOpen={() => setThread(t.id)} />)}
      {live.length < between.length && <p className="hint">{between.length - live.length} finished
        {between.length - live.length === 1 ? ' thread' : ' threads'}: <LinkButton onClick={() => setThread(between.find(t => !live.includes(t))!.id)}>the latest</LinkButton></p>}
    </section>

    {thread !== null && <ThreadModal id={thread} onClose={() => setThread(null)} act={act} />}
    {writing && <WriteModal box={box} onClose={() => setWriting(false)} onSent={() => { setWriting(false); act(Promise.resolve()) }} />}
  </>
}

/** Mail that hasn't reached its colony yet: waiting for the mayor's look, or for room to start */
function Waiting({ title, note, mail, onThread, send }: {
  title: string; note: string; mail: Letter[]; onThread: (id: number) => void; send?: (l: Letter) => void
}) {
  return <div className="t-card">
    <div className="t-meta"><b>{title}</b>{note && <span className="hint">· {note}</span>}</div>
    {mail.map(l => <div key={l.id} className="t-sent">
      <Who a={l.from} /> <span>to</span> <Who a={l.to} />
      <span className="grow"><LinkButton onClick={() => onThread(l.thread_id)}>{l.subject || '(no subject)'}</LinkButton></span>
      <span className="hint">{when(l.created_at)}</span>
      {send && l.state === 'waiting' && <button className="tiny" onClick={() => send(l)} title="Wake this colony now, without waiting for the mayor">Send now</button>}
    </div>)}
  </div>
}

/** Something for you: a question (with its options, or your own words), or something to read */
function Note({ l, act, onThread }: { l: Letter; act: (p: Promise<unknown>) => void; onThread: () => void }) {
  const [text, setText] = useState('')
  const guard = l.kind === 'guard'
  return <div className="t-card mail">
    <div className="t-meta">{guard ? <b>Agent Town</b> : <Who a={l.from} />}
      <span>· {guard ? 'a thread paused' : l.kind === 'question' ? 'asks you' : 'for you to read'} · {when(l.created_at)}</span>
      <span className="grow" /><LinkButton onClick={onThread}>Thread #{l.thread_id}</LinkButton></div>
    <Md text={l.body} />
    {l.kind === 'fyi' ? <div className="row tight"><button className="tiny" onClick={() => act(api.readMail(l.id))}>Done</button></div>
      : <div className="row tight">
        {l.options.map(o => <button key={o} className={o === l.options[0] ? 'primary tiny' : 'tiny'} onClick={() => act(api.answerMail(l.id, o))}>{o}</button>)}
        {!guard && <form className="row tight grow" onSubmit={e => { e.preventDefault(); if (text.trim()) act(api.answerMail(l.id, text.trim())) }}>
          <input className="grow" value={text} onChange={e => setText(e.target.value)} placeholder={l.options.length ? 'Or say something else…' : 'Your answer…'} />
          <button className="tiny" disabled={!text.trim()}>Answer</button></form>}
      </div>}
  </div>
}

function ThreadRow({ t, onOpen }: { t: MailThreadInfo; onOpen: () => void }) {
  return <div className="t-sent">
    <span className="t-who">{t.agents.map(a => <span key={a.id} className="sw" style={{ background: a.color }} title={nice(a.name)} />)}</span>
    <span className="grow"><LinkButton onClick={onOpen}><b>{t.subject || '(no subject)'}</b></LinkButton>
      <span className="hint"> · {t.agents.map(a => nice(a.name)).join(', ')} · {t.messages} message{t.messages === 1 ? '' : 's'}</span></span>
    <span className={`t-state ${t.status === 'paused' ? 'bad' : t.status === 'open' ? 'live' : 'ok'}`}>{STATUS[t.status]}</span>
  </div>
}

function ThreadModal({ id, onClose, act }: { id: number; onClose: () => void; act: (p: Promise<unknown>) => void }) {
  const [t, setT] = useState<(MailThreadInfo & { mail: Letter[] }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.mailThread(id).then(setT, e => setError(msg(e))) }, [id])
  return <Modal title={t ? t.subject || `Thread #${id}` : 'Thread'} onClose={onClose} wide>
    <Err error={error} />
    {t && <>
      <p className="hint">#{t.id} · {STATUS[t.status]}{t.paused_reason && ` (${t.paused_reason})`}
        {t.started_by && <> · started by {nice(t.started_by.name)}</>}{t.parent_id && <> · from thread #{t.parent_id}</>}
        {t.cost_usd > 0 && <> · about ${t.cost_usd.toFixed(2)} on your AI account</>}</p>
      {t.mail.map(l => <div key={l.id} className="t-card">
        <div className="t-meta">{l.kind === 'guard' ? <b>Agent Town</b> : <Who a={l.from} />}<span>to</span><Who a={l.to} />
          <span className="hint">· {when(l.created_at)}</span>
          <span className="grow" /><span className="hint">{l.state === 'waiting' ? 'waiting for the mayor' : l.state === 'queued' ? 'about to go' : l.state === 'held' ? 'held while paused' : ''}</span></div>
        <Md text={l.body} />
        {l.answer && <p><b>Answer:</b> {l.answer}</p>}
      </div>)}
      {t.status !== 'done' && <div className="row"><span className="grow" />
        <button className="danger" onClick={() => { act(api.finishThread(t.id)); onClose() }}>Stop this thread</button></div>}
    </>}
  </Modal>
}

function WriteModal({ box, to: fixed, onClose, onSent }: { box: Mailbox; to?: string; onClose: () => void; onSent: () => void }) {
  const [to, setTo] = useState(fixed ?? box.colonies[0]?.colony ?? '')
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const w = useTeamWord()
  async function send(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try { await api.sendMail({ to, subject, body }); onSent() } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }
  return <Modal title={fixed ? `Write to ${fixed}` : `Write to a ${w.one}`} onClose={onClose}>
    <form className="form" onSubmit={send}>
      {!fixed && <label>To<select value={to} onChange={e => setTo(e.target.value)}>
        {box.colonies.map(c => <option key={c.id} value={c.colony}>{c.colony === c.name ? nice(c.name) : `${c.colony} (${nice(c.name)})`}</option>)}
      </select></label>}
      <label>Subject<input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Competitor check" /></label>
      <label>Message <span className="hint">It goes now: its lead starts on it, and answers by mail.</span>
        <textarea rows={5} value={body} onChange={e => setBody(e.target.value)} required /></label>
      <Err error={error} />
      <div className="row"><button className="primary" disabled={busy || !body.trim() || !to}>Send</button>
        <button type="button" onClick={onClose}>Cancel</button></div>
    </form>
  </Modal>
}

/** Mail an agent was handed, in its chat: who wrote, and what they said (not the instructions around it) */
export function MailNote({ said, className }: { said: MailSaid[]; className: string }) {
  return <div className={className}>
    {said.map((m, i) => <div key={i}>
      <div className="mb-from">✉ Mail from {m.from.replace(/^the person$/, 'you')} · #{m.thread_id} {m.subject}</div>
      <Md text={m.body} />
    </div>)}
  </div>
}

/** A colony's lead came to the square to see you: what it brought (questions first), answered right here.
 *  Once nothing of theirs waits on you, it walks home (the map polls /api/mail/town). */
export function VisitModal({ agentId, onClose, onDone }: { agentId: number; onClose: () => void; onDone: () => void }) {
  const [box, setBox] = useState<Mailbox | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [thread, setThread] = useState<number | null>(null)
  const load = useCallback(() => api.mailbox().then(setBox, e => setError(msg(e))), [])
  useEffect(() => { load() }, [load])
  const theirs = (box?.inbox ?? []).filter(l => l.from?.id === agentId || (l.kind === 'guard' && box?.threads.find(t => t.id === l.thread_id)?.started_by?.id === agentId))
    .sort((a, b) => Number(b.kind !== 'fyi') - Number(a.kind !== 'fyi'))
  const who = theirs.find(l => l.from)?.from
  const act = (p: Promise<unknown>) => p.then(() => { onDone(); return load() }, e => setError(msg(e)))
  useEffect(() => { if (box && !theirs.length) onClose() }, [box, theirs.length, onClose])
  return <Modal title={who ? `${nice(who.name)} came to see you` : 'Came to see you'} onClose={onClose}>
    <Err error={error} />
    {who && who.colony !== who.name && <p className="hint">From the {who.colony} colony.</p>}
    {theirs.map(l => <Note key={l.id} l={l} act={act} onThread={() => setThread(l.thread_id)} />)}
    {thread !== null && <ThreadModal id={thread} onClose={() => setThread(null)} act={act} />}
  </Modal>
}

/** A colony's post office on the map: its mail waiting to be delivered, its threads, and a way to write to it. */
export function PostOfficeCard({ agentId, colony, onClose }: { agentId: number; colony: string; onClose: () => void }) {
  const [box, setBox] = useState<Mailbox | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [thread, setThread] = useState<number | null>(null)
  const [writing, setWriting] = useState(false)
  const load = useCallback(() => api.mailbox(agentId).then(setBox, e => setError(msg(e))), [agentId])
  useEffect(() => { load() }, [load])
  const act = (p: Promise<unknown>) => p.then(load, e => setError(msg(e)))
  const going = box?.threads.filter(t => t.status !== 'done') ?? []
  const w = useTeamWord()
  return <div className="card">
    <button className="x" onClick={onClose} aria-label="Close">×</button>
    <h2>📮 Post office<span className="pill">{colony}</span></h2>
    <p className="tag">Where {colony}'s mail comes and goes: what other {w.many} asked it, and what it asked them.</p>
    <Err error={error} />
    {box && <>
      {box.waiting.length > 0 && <Waiting title={box.waiting.some(l => l.state === 'waiting') && box.mayor ? `Waiting for ${nice(box.mayor.name)}` : 'About to go'}
        note="" mail={box.waiting} onThread={setThread} send={l => act(api.deliverMail(l.id))} />}
      {going.map(t => <ThreadRow key={t.id} t={t} onOpen={() => setThread(t.id)} />)}
      {!box.waiting.length && !going.length && <p className="hint">No mail going right now{box.threads.length ? ` (${box.threads.length} finished)` : ''}.</p>}
      <div className="row tight"><button onClick={() => setWriting(true)}>Write to {colony}</button></div>
      {writing && <WriteModal box={box} to={colony} onClose={() => setWriting(false)} onSent={() => { setWriting(false); load() }} />}
    </>}
    {thread !== null && <ThreadModal id={thread} onClose={() => setThread(null)} act={act} />}
  </div>
}
