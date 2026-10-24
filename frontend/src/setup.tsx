// "Make it your own": right after you add an agent (and any time from its panel). Three plain steps:
// tell it about you, connect the apps it should use, and pick which AI account it thinks with.
// "About you" is only the questions this agent asks for its own job (its `ask:`), saved as about-me.md.
// Who you are and what your company does lives in your profile, which every agent reads (profile.tsx).

import { useEffect, useState } from 'react'
import { api, type City, type Connection, type GoogleStatus, type LinkedInStatus, type MyAgent } from './api'
import { useCredentials } from './hooks'
import { APPS, connectionFor, signIn, suggestedApps, type App } from './connectors'
import { BrainPicker } from './cards'
import { hasAnswers, parseAnswers, useProfile, writeAnswers, type Answers } from './profile'
import { Err, LinkButton, Modal, msg } from './ui'

const FILE = 'about-me.md'

export function SetupModal({ agent, city, reload, onClose, onChat, onAccount, onAdvanced, onProfile, initialStep = 0 }: {
  agent: MyAgent; city: City; reload: () => Promise<void>; onClose: () => void
  onChat: () => void; onAccount: () => void; onAdvanced: () => void; onProfile: () => void; initialStep?: number
}) {
  const [step, setStep] = useState(initialStep)
  const [questions, setQuestions] = useState<string[] | null>(null)
  const [market, setMarket] = useState<string[] | undefined>(undefined)
  const previous = agent.files.find(f => f.path === FILE)?.content ?? ''
  const [answers, setAnswers] = useState<Answers>(() => parseAnswers(previous))
  const profile = useProfile(city)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.market().then(m => {
      const e = m.find(x => x.name === agent.name)
      setQuestions(e?.ask ?? []); setMarket(e?.tools)
    }).catch(() => setQuestions([]))                // no market, or an older server: the profile is enough
  }, [agent.name])

  // nothing of its own to ask: straight to its apps
  const ready = questions !== null
  useEffect(() => {
    if (ready && step === 0 && initialStep === 0 && !questions.length) setStep(1)
  }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps

  async function saveAbout() {
    const qs = questions ?? []
    if (hasAnswers(qs, answers)) await api.putFile(agent.id, FILE, writeAnswers('About me', qs, answers, previous))
  }

  async function next() {
    setBusy(true); setError(null)
    try {
      if (step === 0 && ready) await saveAbout()
      await reload()
      if (step < 2) setStep(step + 1)
      else onChat()
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }

  const steps = ['About you', 'Apps', 'Its brain']
  return (
    <Modal title={`Make ${agent.name} your own`} onClose={onClose} wide>
      <ol className="setup-steps">{steps.map((s, i) => <li key={s} className={i === step ? 'on' : i < step ? 'done' : ''}>{s}</li>)}</ol>

      {step === 0 && !ready && <p className="hint">Loading…</p>}
      {step === 0 && ready && <div className="form">
        {questions.length > 0 && <>
          <p className="hint">A few answers make {agent.name} more useful. Only {agent.name} reads them. Skip any.</p>
          {questions.map((q, i) => (
            <label key={q}>{q}
              <textarea id={`about-${i}`} rows={q.toLowerCase().includes('paste') ? 4 : 2} value={answers[q] ?? ''}
                onChange={e => setAnswers({ ...answers, [q]: e.target.value })} /></label>))}
        </>}
        <p className="hint profile-line">{profile.filled
          ? <>✓ Your agents know you and your company. <LinkButton onClick={onProfile}>Edit</LinkButton></>
          : <>Tell every agent who you are: <LinkButton onClick={onProfile}>add your website or bio</LinkButton>.</>}</p>
      </div>}

      {step === 1 && <>
        <p className="hint">{agent.name} only gets the apps you tick. Change it any time.
          {agent.team.length > 0 && <> Its team gets the apps they need too.</>}</p>
        <AppList city={city} agent={agent} suggested={suggestedApps(agent, market)} reload={reload} onAdvanced={onAdvanced} />
      </>}

      {step === 2 && <Brain agent={agent} reload={reload} onAccount={onAccount} />}

      <Err error={error} />
      <div className="row">
        {step > 0 && <button onClick={() => setStep(step - 1)}>Back</button>}
        <span className="grow" />
        {step < 2 && <button onClick={() => setStep(step + 1)}>Skip</button>}
        <button className="primary" disabled={busy} onClick={next}>{step < 2 ? 'Next' : `Done: say hi to ${agent.name}`}</button>
      </div>
    </Modal>
  )
}

/** Apps you can connect; with an agent, also whether that agent may use each one. */
export function AppList({ city, agent, suggested, reload, onAdvanced }: {
  city: City; agent?: MyAgent; suggested?: App[]; reload: () => Promise<void>; onAdvanced: () => void
}) {
  const [all, setAll] = useState(!suggested?.length)
  const [error, setError] = useState<string | null>(null)
  const [google, setGoogle] = useState<GoogleStatus | null>(null)
  useEffect(() => { api.googleStatus().then(setGoogle, () => setGoogle(null)) }, [city])
  const [linkedin, setLinkedIn] = useState<LinkedInStatus | null>(null)
  useEffect(() => { api.linkedinStatus().then(setLinkedIn, () => setLinkedIn(null)) }, [city])
  const top = suggested?.length ? suggested : APPS
  const rest = APPS.filter(a => !top.includes(a))
  // the Google apps it's meant to use and doesn't have yet: one Google sign-in connects them all
  const googleWant = top.filter(a => a.google && !connectionFor(a, city.connections)).map(a => a.google!)
  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await reload() } catch (e) { setError(msg(e)) }
  }
  return (
    <div className="apps">
      {top.map(a => <AppRow key={a.key} app={a} city={city} agent={agent} run={run} onAdvanced={onAdvanced} google={google} linkedin={linkedin}
        together={a.google && googleWant.includes(a.google) ? googleWant : undefined} />)}
      {rest.length > 0 && (all
        ? rest.map(a => <AppRow key={a.key} app={a} city={city} agent={agent} run={run} onAdvanced={onAdvanced} google={google} linkedin={linkedin} />)
        : <button className="linklike-btn" onClick={() => setAll(true)}>More apps</button>)}
      {!agent && google && google.accounts.length > 0 && <div className="google-accounts">
        <h3>Google accounts</h3>
        {google.accounts.map(g => <div key={g.id} className="app-row">
          <span className="app-icon" aria-hidden="true">G</span>
          <div className="grow"><b>{g.email}</b><div className={`meta ${g.status === 'connected' ? 'ok' : 'warn'}`}>
            {g.status === 'connected' ? `Connected: ${g.apps.map(x => x === 'gmail' ? 'Gmail' : 'Calendar').join(' and ')}` : 'Signed out: connect it again'}</div></div>
          <button onClick={() => { if (confirm(`Disconnect ${g.email}? Agents lose access to its Gmail and Calendar.`)) run(() => api.disconnectGoogle(g.id)) }}>Disconnect</button>
          {g.apps.includes('gmail') && <div className="email-index">
            <label className="check"><input type="checkbox" checked={g.index.on} onChange={e => {
              if (e.target.checked || confirm('Turn off the email index? Agents lose "who is this?" and open threads, and Today stops showing email waiting on you. What it stored is deleted now.'))
                run(() => api.setEmailIndex(g.id, e.target.checked).then(() => api.googleStatus().then(setGoogle)))
            }} />Remember who I email</label>
            <div className="hint">Who you email and which threads await a reply, from the last 90 days. Senders, dates and subjects
              only (encrypted), never what emails say. Lets agents find people and follow up.{' '}
              {g.index.on && (g.index.problem ? <span className="t-bad">{g.index.problem}</span>
                : g.index.synced_at ? `${g.index.people} people you've written to, updated ${new Date(g.index.synced_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.`
                : 'Building it now (a few minutes).')}</div>
          </div>}
        </div>)}
      </div>}
      {!agent && linkedin && linkedin.accounts.length > 0 && <div className="google-accounts">
        <h3>LinkedIn</h3>
        {linkedin.accounts.map(l => <div key={l.id} className="app-row">
          <span className="app-icon" aria-hidden="true">💼</span>
          <div className="grow"><b>{l.email}</b><div className={`meta ${l.status === 'connected' ? 'ok' : 'warn'}`}>
            {l.status === 'connected'
              ? `Connected${l.expires_at ? ` until ${new Date(l.expires_at).toLocaleDateString([], { day: 'numeric', month: 'short' })}: LinkedIn makes you sign in again every 60 days` : ''}`
              : 'Signed out: connect it again'}</div></div>
          <button onClick={() => { if (confirm(`Disconnect LinkedIn (${l.email})? Agents can't post for you any more.`)) run(() => api.disconnectLinkedIn(l.id)) }}>Disconnect</button>
        </div>)}
      </div>}
      <Err error={error} />
      <p className="hint">Using something else? <LinkButton onClick={onAdvanced}>Connect any app that speaks MCP</LinkButton> (advanced).</p>
    </div>
  )
}

/** Off to Google's (or LinkedIn's) consent screen; when we come back, reopen "Make it your own" on the Apps step.
 * `together`: the Google apps to ask for in one go (Gmail and Calendar for an assistant). */
function signInHosted(app: App, agent?: MyAgent, together?: string[]) {
  try { if (agent) sessionStorage.setItem('agenttown.resumeSetup', String(agent.id)) } catch { /* private mode */ }
  const q = new URLSearchParams(app.google ? { apps: (together ?? [app.google]).join(',') } : {})
  if (agent) q.set('agent', String(agent.id))                     // it gets access once connected
  window.location.href = `/api/connect/${app.google ? 'google' : 'linkedin'}/start?${q}`
}

function AppRow({ app, city, agent, run, onAdvanced, google, linkedin, together }: {
  app: App; city: City; agent?: MyAgent; run: (fn: () => Promise<unknown>) => Promise<void>; onAdvanced: () => void
  google: GoogleStatus | null; linkedin: LinkedInStatus | null; together?: string[]
}) {
  const [token, setToken] = useState('')
  const [open, setOpen] = useState(false)
  const conn: Connection | undefined = connectionFor(app, city.connections)
  const granted = !!(agent && conn && agent.grants.some(g => g.connection_id === conn.id))
  const toggle = () => agent && conn && run(() => api.setGrants(agent.id, granted
    ? agent.grants.filter(g => g.connection_id !== conn.id)
    : [...agent.grants.filter(g => g.connection_id !== conn.id), { connection_id: conn.id, tool_name: null }]))

  const hosted = app.how === 'google' ? google : app.how === 'linkedin' ? linkedin : null   // sign-in Agent Town runs itself
  const who = app.how === 'google' ? 'Google' : 'LinkedIn'
  let action, note = ''
  if (conn && conn.status === 'auth_required' && (app.how === 'google' || app.how === 'linkedin')) {
    action = <button className="primary" onClick={() => signInHosted(app, agent)}>Connect again</button>
    note = ` Its ${who} sign-in expired.`
  } else if (conn && conn.status === 'auth_required' && conn.sign_in !== 'none') {
    action = <button className="primary" onClick={() => signIn(conn, agent)}>Sign in{conn.sign_in === 'signed_in' ? ' again' : ''}</button>
    note = ` ${conn.status_detail}.`
  } else if (conn) {
    const ok = conn.status === 'connected' || conn.status === 'needs_sandbox'
    action = agent
      ? <label className="check"><input type="checkbox" checked={granted} onChange={toggle} /> Let it use {app.name}</label>
      : <span className={`meta ${ok ? 'ok' : 'warn'}`}>{ok ? 'Connected' : conn.status_detail || 'Needs attention'}</span>
  } else if (app.how === 'google' || app.how === 'linkedin') {
    const here = typeof window !== 'undefined' ? window.location.origin : ''
    if (!hosted?.configured) { action = <span className="meta soon">Not set up yet</span>; note = ` This server's owner hasn't added a ${who} app yet.` }
    else if (hosted.app_url !== here) { action = <a className="button" href={hosted.app_url}>Connect at {new URL(hosted.app_url).host}</a>; note = ` ${who} sends you back to ${new URL(hosted.app_url).host}.` }
    else action = <button className="primary" onClick={() => signInHosted(app, agent, together)}
      title={together && together.length > 1 ? 'One Google sign-in connects Gmail and Calendar' : undefined}>Connect</button>
  } else if (app.how === 'oauth') {
    action = <button className="primary" onClick={() => run(async () => {
      const c = await api.addConnection({ name: app.name, transport: 'http', url: app.url })
      if (c.status === 'connected') { if (agent) await api.setGrants(agent.id, [...agent.grants, { connection_id: c.id, tool_name: null }]) }
      else if (c.sign_in === 'available') signIn(c, agent)
      else throw new Error(`${app.name}: ${c.status_detail}`)
    })}>Connect</button>
  } else if (app.how === 'token') {
    action = <button className="primary" onClick={() => setOpen(!open)}>Connect</button>
  } else if (app.how === 'custom') {
    action = <button onClick={onAdvanced}>Connect…</button>
  } else {
    action = <span className="meta soon">Coming soon</span>
  }

  return (
    <div className={`app-row${app.how === 'soon' && !conn ? ' muted' : ''}`}>
      <span className="app-icon" aria-hidden="true">{app.icon}</span>
      <div className="grow"><b>{app.name}</b><div className="meta wrap">Lets it {app.does}.{app.how === 'soon' && !conn && ' One-click sign-in is on its way.'}{note}</div></div>
      {action}
      {open && !conn && <div className="app-connect">
        <p className="hint">{app.tokenHelp} <a href={app.tokenLink} target="_blank" rel="noreferrer">Open {app.name}</a></p>
        <div className="row tight">
          <input className="note" type="password" autoComplete="off" placeholder={`Paste your ${app.name} token`} value={token} onChange={e => setToken(e.target.value)} />
          <button className="primary" disabled={!token} onClick={() => run(async () => {
            const c = await api.addConnection({ name: app.key, transport: 'http', url: app.url, auth_header: `Bearer ${token.trim()}` })
            if (c.status !== 'connected') throw new Error(`${app.name} didn't accept that: ${c.status_detail}`)
            if (agent) await api.setGrants(agent.id, [...agent.grants, { connection_id: c.id, tool_name: null }])
            setToken(''); setOpen(false)
          })}>Connect</button>
        </div>
        <p className="hint">Stored encrypted and never shown again.</p>
      </div>}
    </div>
  )
}

function Brain({ agent, reload, onAccount }: { agent: MyAgent; reload: () => Promise<void>; onAccount: () => void }) {
  const { creds } = useCredentials()
  if (creds === null) return <p className="hint">Checking your accounts…</p>
  if (!creds.length) return (
    <div className="brain">
      <p><b>{agent.name} needs an AI to think with.</b> Connect Claude or ChatGPT once, for all your agents.</p>
      <button className="primary" onClick={onAccount}>Connect your AI</button>
    </div>)
  const run = async (fn: () => Promise<unknown>) => { await fn(); await reload() }
  return (
    <div className="brain">
      <p>Pick how {agent.name} thinks. Bigger and longer is smarter, but slower and uses more of your plan.</p>
      <BrainPicker agent={agent} run={run} />
      <p className="hint">That's it. Change this any time in the chest in its house.</p>
    </div>)
}
