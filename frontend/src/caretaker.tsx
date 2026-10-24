// The caretaker: Agent Town's own helper behind the "?" button (backend/app/caretaker.py). Not one of your
// agents and not on the map: it knows the app, sees your town, and changes it at once, with an Undo on every
// answer that changed something. Agents and colonies it suggests wait for your Add, like an agent's.
// It thinks with your own Claude. On an API key it answers in one request; on a subscription it works in
// its own sandbox (Claude Code), so the message comes back "working" and the panel checks until it's done.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, ApiError, type CaretakerAction, type CaretakerTurn, type MapBuilding } from './api'
import { MailCard } from './mail'
import { Err, Md, msg } from './ui'

const EXAMPLES = [
  'Put each colony\'s houses together, leads in front',
  'How do I connect Gmail?',
  'Make the map look like a fantasy map',
  'What agent would help me write a weekly newsletter?',
]

export function CaretakerPanel({ snapshot, theme, aiVersion, onActions, onScreen, onChanged, onConnectAi, onClose }: {
  snapshot: () => MapBuilding[]; theme: string; aiVersion: number
  onActions: (actions: CaretakerAction[]) => void            // focus a building: done as soon as it answers
  onScreen: (action: Extract<CaretakerAction, { type: 'open' }>) => void   // a screen it offered: done when you press its button
  onChanged: () => void; onConnectAi: () => void; onClose: () => void
}) {
  const office = theme === 'office'                               // the Office has cabins, not houses
  const [ready, setReady] = useState<boolean | null>(null)
  const [why, setWhy] = useState('')
  const [turns, setTurns] = useState<CaretakerTurn[]>([])
  const [text, setText] = useState('')
  const [asking, setAsking] = useState<string | null>(null)   // what you said, while it thinks
  const [error, setError] = useState<string | null>(null)
  const [via, setVia] = useState('')
  const log = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    api.caretaker().then(d => { setReady(d.ready); setWhy(d.why); setVia(d.via); setTurns(d.turns) }, e => setError(msg(e)))
  }, [aiVersion])

  // a message its sandbox is working on: look again every second and a half until it's answered,
  // then do what it asked (show a building) and redraw the town if it changed something
  const working = turns.find(t => t.state === 'working')
  useEffect(() => {
    if (!working) return
    const id = working.id
    const t = window.setInterval(async () => {
      try {
        const d = await api.caretaker()
        setTurns(d.turns)
        const done = d.turns.find(x => x.id === id)
        if (done && done.state !== 'working') {
          onActions(done.actions)
          if (done.changed || done.proposals.length) onChanged()
        }
      } catch (e) { setError(msg(e)) }
    }, 1500)
    return () => clearInterval(t)
  }, [working?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight }) }, [turns, asking])
  useEffect(() => { if (ready) box.current?.focus() }, [ready])
  useLayoutEffect(() => {                  // the box grows with what you type, like the chat's
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`
  }, [text])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !(e.target as HTMLElement).closest?.('.modal')) onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const act = useCallback(async (p: Promise<{ turns: CaretakerTurn[] }>, changed: boolean) => {
    setError(null)
    try { setTurns((await p).turns); if (changed) onChanged() } catch (e) { setError(msg(e)) }
  }, [onChanged])

  async function ask(e?: React.FormEvent, said = text) {
    e?.preventDefault()
    const t = said.trim()
    if (!t || asking) return
    setAsking(t); setText(''); setError(null)
    try {
      const r = await api.askCaretaker(t, snapshot(), theme)
      setTurns(r.turns)
      const fresh = r.turns[r.turns.length - 1]
      if (fresh && fresh.state !== 'working') {
        onActions(fresh.actions)
        if (fresh.changed) onChanged()
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) { setReady(false); setWhy(err.message) } else setError(msg(err))
      setText(t)                           // nothing was lost: try again
    } finally { setAsking(null) }
  }

  return (
    <aside className="caretaker" role="dialog" aria-label="Help with Agent Town">
      <div className="ct-head">
        <h2>Caretaker</h2>
        <span className="hint">help with Agent Town</span>
        <span className="grow" />
        {turns.length > 0 && <button onClick={() => act(api.restartCaretaker(), false)} title="Begin a new conversation">Start over</button>}
        <button className="x" onClick={onClose} aria-label="Close (Esc)">×</button>
      </div>
      <div className="ct-log" ref={log}>
        {turns.length === 0 && !asking && <div className="ct-intro">
          <p>Hi! I look after Agent Town. Ask me how anything works, or ask me to change your town:</p>
          {(office ? ['Which cabin is my newsletter agent in?', ...EXAMPLES.slice(1)] : EXAMPLES).map(x => <button key={x} className="ct-example" disabled={!ready} onClick={() => ask(undefined, x)}>{x}</button>)}
          <p className="hint">What I change happens at once, and every change has an Undo. New agents wait for your Add.
            I think with your own Claude{via === 'subscription' ? ' subscription: my first answer takes a few seconds while I wake up' : ''}.</p>
        </div>}
        {turns.map(t => <div key={t.id} className="ct-turn">
          <p className="ct-you">{t.text}</p>
          {t.reply && <div className={`ct-reply${t.state === 'failed' ? ' err' : ''}`}><Md text={t.reply} /></div>}
          {t.state === 'working' && <p className="dlg-act typing">Thinking<span>.</span><span>.</span><span>.</span></p>}
          {t.proposals.map(p => <MailCard key={p.id} e={p} who="The caretaker" className="dlg-mail"
            onDecide={add => act(api.decideCaretaker(t.id, p.id, add), add)} />)}
          {(t.actions.some(a => a.type === 'open') || t.changed) && <div className="ct-row">
            {t.actions.map((a, i) => a.type === 'open' && <button key={i} className="primary" onClick={() => onScreen(a)}>{a.label} →</button>)}
            {t.changed && (t.undone ? <span className="hint">Undone</span>
              : t.can_undo ? <button onClick={() => act(api.undoCaretaker(t.id), true)} title="Put back everything this answer changed">Undo</button>
              : <span className="hint">Changed your town</span>)}
          </div>}
        </div>)}
        {asking && <div className="ct-turn"><p className="ct-you">{asking}</p>
          <p className="dlg-act typing">Thinking<span>.</span><span>.</span><span>.</span></p></div>}
      </div>
      <Err error={error} />
      {ready === false ? <div className="ct-key">
        <p>{why}</p>
        <button className="primary" onClick={onConnectAi}>Connect your Claude/ChatGPT</button>
      </div> : <form className="dlg-input" onSubmit={ask}>
        <textarea ref={box} value={text} rows={1} placeholder="Ask the caretaker…" disabled={!ready}
          onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }} />
        <button className="primary" disabled={!ready || !text.trim() || !!asking || !!working}>Ask</button>
      </form>}
    </aside>
  )
}
