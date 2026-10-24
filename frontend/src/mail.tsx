// An email an agent sent, or a LinkedIn post, wherever it shows (the chat, Today). Its state is decided
// on the server (backend/app/outbox.py): waiting for your Send, going out by the agent's rules after a
// short wait you can cancel, or done. A post has no wait: it's out already, or waiting for your Post.
// An agent or colony an agent proposes for your town always waits for your Add (backend/app/town.py).

import { useTeamWord } from './look'
import { useEffect, useState, type ReactNode } from 'react'
import type { RunEvent } from './api'
import { safeHref } from './ui'

/** Seconds until `iso`, ticking down once a second */
function useLeft(iso: string | null): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!iso) return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [iso])
  return iso ? Math.max(0, Math.ceil((new Date(iso).getTime() - now) / 1000)) : 0
}

export function MailCard({ e, who, extra, className, onDecide }: {
  e: RunEvent; who: ReactNode; extra?: ReactNode; className: string; onDecide: (send: boolean) => void
}) {
  const s = (k: string) => String(e.data[k] ?? '')
  const state = s('state')
  const left = useLeft(state === 'scheduled' ? s('send_at') : null)
  if (s('type') === 'agent' || s('type') === 'colony') return <TownCard e={e} who={who} extra={extra} className={className} onDecide={onDecide} />
  if (s('type') === 'post') return <PostCard e={e} who={who} extra={extra} className={className} onDecide={onDecide} />
  const head = state === 'pending' ? <>{who} wants to send this from your Gmail</>
    : state === 'scheduled' ? <>{who} is sending this from your Gmail, as its rules allow</>
    : <>{who} wrote this from your Gmail</>
  return <div className={`${className} ${state}`}>
    <div className="meta">{head}{extra}:</div>
    <div><b>To:</b> {s('to')}{s('cc') && <> · <b>Cc:</b> {s('cc')}</>}</div>
    <div><b>Subject:</b> {s('subject') || '(none)'}</div>
    <pre>{s('body')}</pre>
    {state === 'pending' && <>
      {s('why') && <div className="meta why">Asking you because: {s('why')}</div>}
      <div className="row tight"><button className="primary" onClick={() => onDecide(true)}>Send</button>
        <button onClick={() => onDecide(false)}>Don't send</button>
        <span className="hint">Don't send keeps it in your Gmail Drafts to edit.</span></div>
    </>}
    {state === 'scheduled' && <div className="row tight">
      <span className="meta">{left > 0 ? `Goes out in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : 'Going out now…'}</span>
      <button onClick={() => onDecide(false)}>Cancel</button>
      <button onClick={() => onDecide(true)}>Send now</button></div>}
    {state === 'sent' && <div className="meta">✓ Sent{e.data.auto ? ' on its own, by its rules' : ''}</div>}
    {state === 'declined' && <div className="meta">Not sent: still in your Drafts</div>}
    {state === 'cancelled' && <div className="meta">Cancelled: still in your Drafts</div>}
  </div>
}

function PostCard({ e, who, extra, className, onDecide }: {
  e: RunEvent; who: ReactNode; extra?: ReactNode; className: string; onDecide: (post: boolean) => void
}) {
  const s = (k: string) => String(e.data[k] ?? '')
  const state = s('state')
  const to = s('visibility') === 'CONNECTIONS' ? 'your connections' : 'everyone'
  return <div className={`${className} ${state}`}>
    <div className="meta">{state === 'pending' ? <>{who} wants to post this on your LinkedIn</> : <>{who} wrote this for your LinkedIn</>}{extra}:</div>
    <div><b>Seen by:</b> {to}</div>
    <pre>{s('text')}</pre>
    {state === 'pending' && <>
      {s('why') && <div className="meta why">Asking you because: {s('why')}</div>}
      <div className="row tight"><button className="primary" onClick={() => onDecide(true)}>Post</button>
        <button onClick={() => onDecide(false)}>Don't post</button></div>
    </>}
    {state === 'sent' && <div className="meta">✓ Posted{e.data.auto ? ' on its own, by its rules' : ''}
      {safeHref(s('url')) && <> · <a href={safeHref(s('url'))} target="_blank" rel="noopener noreferrer">See it on LinkedIn</a></>}</div>}
    {state === 'declined' && <div className="meta">Not posted</div>}
  </div>
}

function TownCard({ e, who, extra, className, onDecide }: {
  e: RunEvent; who: ReactNode; extra?: ReactNode; className: string; onDecide: (add: boolean) => void
}) {
  const s = (k: string) => String(e.data[k] ?? '')
  const state = s('state'), agent = s('type') === 'agent'
  const members = Array.isArray(e.data.members) ? e.data.members.map(String) : []
  const w = useTeamWord()
  return <div className={`${className} ${state}`}>
    <div className="meta">{who} {state === 'pending' ? 'wants to add' : 'proposed'} {agent ? 'an agent' : `a ${w.one}`} to your {w.one === 'cabin' ? 'office' : 'town'}{extra}:</div>
    {agent ? <>
      <div><b>{s('name')}</b>{s('colony') && <span className="hint"> · joins {s('colony')}</span>}</div>
      <div>{s('description')}</div>
      <details><summary className="hint">Its instructions</summary><pre>{s('instructions')}</pre></details>
    </> : <>
      <div><b>{s('name')}</b>{s('about') && <>: {s('about')}</>}</div>
      {s('lead') ? <div><b>Lead:</b> {s('lead')} · <b>Team:</b> {members.length ? members.join(', ') : <span className="hint">none yet, just its lead</span>}</div>
        : <div className="hint">{w.one === 'cabin' ? 'An empty cabin: a named room in your office, its agents to come.' : 'An empty colony: a named plot on your map, its agents to come.'}</div>}
    </>}
    {state === 'pending' && <div className="row tight"><button className="primary" onClick={() => onDecide(true)}>Add</button>
      <button onClick={() => onDecide(false)}>Not now</button></div>}
    {state === 'sent' && <div className="meta">✓ Added to your town</div>}
    {state === 'declined' && <div className="meta">Not added</div>}
  </div>
}
