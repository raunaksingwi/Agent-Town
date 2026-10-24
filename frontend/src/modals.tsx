import { useEffect, useState } from 'react'
import { usePlain } from './look'
import { api, type Connection } from './api'
import { pairs, signIn } from './connectors'
import { Err, LinkButton, Modal, msg, readFiles } from './ui'

export function AuthModal({ mode: initial, error: initialError = null, onClose, onDone }: {
  mode: 'login' | 'signup'; error?: string | null; onClose: () => void; onDone: (mode: 'login' | 'signup') => void
}) {
  const [mode, setMode] = useState(initial)
  const [google, setGoogle] = useState(false)     // can this server sign in with Google? (shown once it says so)
  const [passwordSignup, setPasswordSignup] = useState(true)   // or are new accounts Google-only?
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [assistant, setAssistant] = useState('')
  const [error, setError] = useState<string | null>(initialError)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api.authOptions().then(o => { setGoogle(o.google); setPasswordSignup(o.password_signup) }, () => setGoogle(false))
  }, [])
  const passwordForm = mode === 'login' || passwordSignup

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      if (mode === 'signup') await api.signup(email, username, password, assistant)
      else await api.login(email, password)
      onDone(mode)
    } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }
  const switchTo = (m: 'login' | 'signup') => { setMode(m); setError(null) }

  // Both ways on one screen: Google on top (a full page visit there and back, routers/auth.py, not a
  // fetch), then email and password. The mayor's name sits above both, since either makes the account.
  // A server can make new accounts Google-only (AGENTTOWN_PASSWORD_SIGNUP=false): signing up is then
  // just the button, while signing in keeps the password form for accounts that already have one.
  return (
    <Modal title={mode === 'signup' ? 'Create your account' : 'Sign in'} onClose={onClose}>
      <form onSubmit={submit} className="form">
        {mode === 'signup' && <AssistantName value={assistant} onChange={setAssistant} />}
        {google && <>
          <button type="button" className="primary google" disabled={busy} onClick={() => {
            setBusy(true)
            window.location.href = '/api/auth/google' + (mode === 'signup' && assistant.trim() ? `?assistant=${encodeURIComponent(assistant.trim())}` : '')
          }}><GoogleMark /> Continue with Google</button>
          <p className="hint">{mode === 'signup'
            ? 'Your @name comes from your first name; change it any time under your account.'
            : 'New here? The same button makes your account.'}</p>
          {passwordForm && <div className="or">or with email</div>}
        </>}
        {!passwordForm && !google && <p className="hint">New accounts can't be made on this server right now.</p>}
        {!passwordForm && <Err error={error} />}
        {passwordForm && <>
          <label>{mode === 'signup' ? 'Email' : 'Email or username'}
            <input value={email} onChange={e => setEmail(e.target.value)} type={mode === 'signup' ? 'email' : 'text'} required /></label>
          {mode === 'signup' && <label>Username <span className="hint">lowercase, 3–30 chars: your district's name</span>
            <input value={username} onChange={e => setUsername(e.target.value.toLowerCase())} pattern="[a-z0-9][a-z0-9_-]{2,29}" required /></label>}
          <label>Password {mode === 'signup' && <span className="hint">8+ characters</span>}
            <input value={password} onChange={e => setPassword(e.target.value)} type="password" minLength={mode === 'signup' ? 8 : 1} required /></label>
          <Err error={error} />
          <button className={google ? '' : 'primary'} disabled={busy}>{mode === 'signup' ? 'Create account' : 'Sign in'}</button>
        </>}
        <p className="switch">{mode === 'signup' ? 'Have an account? ' : 'New here? '}
          <LinkButton onClick={() => switchTo(mode === 'signup' ? 'login' : 'signup')}>
            {mode === 'signup' ? 'Sign in' : 'Create an account'}</LinkButton></p>
      </form>
    </Modal>
  )
}

/** Google's "G", as its sign-in button guidelines ask for */
function GoogleMark() {
  return <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
  </svg>
}

/** What they'll call their mayor, the one agent a new town starts with; empty means Mayor. */
export function AssistantName({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const office = usePlain()
  return <label>Name your mayor <span className="hint">{office ? 'it works at reception' : 'it walks with you'}, shows you around and builds your agents with you</span>
    <input value={value} onChange={e => onChange(e.target.value)} placeholder="Mayor" maxLength={30} /></label>
}

const TEMPLATE = `---
name: my-agent
description: What this agent does, in one line.
---

# My agent

You are … Describe how it should behave, what it knows, and what it must not do.
`

export function NewAgentModal({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const [markdown, setMarkdown] = useState(TEMPLATE)
  const [name, setName] = useState('')
  const [extra, setExtra] = useState<{ path: string; content: string }[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function pickDefinition(list: FileList | null) {
    const [f] = await readFiles(list)
    if (f) setMarkdown(f.content)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const a = await api.createAgent(markdown, name || null, extra)
      onDone(a.id)
    } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }

  return (
    <Modal title="New agent" onClose={onClose} wide>
      <form onSubmit={submit} className="form">
        <p className="hint">An agent is a markdown file, like a Claude Code agent in <code>.claude/agents/</code>.
          It becomes a building in your private district: one floor per file, taller for longer files.</p>
        <label>AGENT.md <span className="hint">paste it, or <label className="linklike">load a .md file<input type="file" accept=".md,.txt" hidden onChange={e => pickDefinition(e.target.files)} /></label></span>
          <textarea value={markdown} onChange={e => setMarkdown(e.target.value)} rows={12} spellCheck={false} /></label>
        <label>Name <span className="hint">optional when the frontmatter has <code>name:</code></span>
          <input value={name} onChange={e => setName(e.target.value)} /></label>
        <label>Knowledge files <span className="hint">optional .md / .txt: extra floors the agent can read</span>
          <input type="file" multiple accept=".md,.txt" onChange={async e => setExtra(await readFiles(e.target.files))} /></label>
        {extra.length > 0 && <p className="hint">{extra.map(f => f.path).join(', ')}</p>}
        <Err error={error} />
        <button className="primary" disabled={busy}>Build it</button>
      </form>
    </Modal>
  )
}

type Mode = 'http' | 'stdio' | 'web' | 'paste'

export function NewToolModal({ onClose, onDone }: { onClose: () => void; onDone: (id: number) => void }) {
  const [name, setName] = useState('')
  const [mode, setMode] = useState<Mode>('http')
  const [url, setUrl] = useState('')
  const [command, setCommand] = useState('')
  const [auth, setAuth] = useState('')
  const [headers, setHeaders] = useState('')
  const [env, setEnv] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [config, setConfig] = useState('')
  const [imported, setImported] = useState<{ added: (Connection & { warnings: string[] })[]; problems: { name: string; detail: string }[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      if (mode === 'paste') { setImported(await api.importConnections(config)); return }
      const c = await api.addConnection(
        mode === 'web' ? { name, transport: 'web', url, auth_header: auth || undefined }
        : mode === 'http' ? { name, transport: 'http', url, headers: pairs(headers, ':'),
                              oauth_client_id: clientId || undefined, oauth_client_secret: clientSecret || undefined }
        : { name, transport: 'stdio', command, env: pairs(env, '=') })
      if (c.status === 'auth_required' && c.sign_in === 'available') signIn(c)   // off to the app's sign-in page
      else onDone(c.id)
    } catch (err) { setError(msg(err)) } finally { setBusy(false) }
  }

  if (imported) return (
    <Modal title="Imported" onClose={() => imported.added.length ? onDone(imported.added[0].id) : onClose()}>
      <ul className="list">{imported.added.map(c => (
        <li key={c.id}><span className={`dot ${c.status}`} /><span className="grow"><b>{c.name}</b>
          <div className="meta wrap">{c.status === 'auth_required' && c.sign_in !== 'none' ? 'Needs you to sign in: open it on the map' : c.status_detail}</div>
          {c.warnings.map((w, i) => <div key={i} className="meta warn wrap">{w}</div>)}</span></li>))}
        {imported.problems.map((p, i) => <li key={`p${i}`}><span className="dot error" /><span className="grow"><b>{p.name}</b><div className="meta wrap">{p.detail}</div></span></li>)}
      </ul>
      <p className="hint">Each one is now a building in your town. Open it to sign in, add what's missing, or see its tools;
        then let your agents use it from their houses.</p>
      <button className="primary" onClick={() => imported.added.length ? onDone(imported.added[0].id) : onClose()}>Done</button>
    </Modal>
  )

  return (
    <Modal title="Connect any app" onClose={onClose}>
      <form onSubmit={submit} className="form">
        <p className="hint">Anything Claude or Codex can use: an MCP server on the web, one you start with a command, or a whole config
          you already have. Agent Town connects, lists its tools, and you choose which agents may use which.</p>
        <div className="seg">
          <button type="button" className={mode === 'http' ? 'on' : ''} onClick={() => setMode('http')}>Web address</button>
          <button type="button" className={mode === 'stdio' ? 'on' : ''} onClick={() => setMode('stdio')}>Command</button>
          <button type="button" className={mode === 'paste' ? 'on' : ''} onClick={() => setMode('paste')}>Paste a config</button>
          <button type="button" className={mode === 'web' ? 'on' : ''} onClick={() => setMode('web')}>Web API</button>
        </div>
        {mode !== 'paste' && <label>Name<input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="notion" required /></label>}
        {mode === 'http' && <>
          <label>Server URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://mcp.example.com/mcp" required /></label>
          <p className="hint">If the app has its own sign-in (most do), you'll go there next, as with Claude's connectors.</p>
          <label>Headers <span className="hint">optional, one per line, e.g. <code>Authorization: Bearer sk-…</code>. Stored encrypted, never shown again</span>
            <textarea rows={2} value={headers} onChange={e => setHeaders(e.target.value)} placeholder="Authorization: Bearer …" spellCheck={false} /></label>
          <details><summary className="hint">The app won't let Agent Town sign in on its own?</summary>
            <p className="hint">Some apps want you to make an OAuth app in their developer settings first. Use the redirect URL
              <code> {window.location.origin}/api/connect/mcp/callback</code>, then paste its client ID (and secret, if it has one).</p>
            <div className="row tight">
              <input className="note" value={clientId} onChange={e => setClientId(e.target.value)} placeholder="Client ID" autoComplete="off" />
              <input className="note" value={clientSecret} onChange={e => setClientSecret(e.target.value)} placeholder="Client secret" type="password" autoComplete="off" />
            </div>
          </details>
        </>}
        {mode === 'stdio' && <>
          <label>Command<input value={command} onChange={e => setCommand(e.target.value)} placeholder="npx -y @modelcontextprotocol/server-filesystem /data" required /></label>
          <label>Environment <span className="hint">optional, one per line, e.g. <code>API_KEY=…</code>. Stored encrypted</span>
            <textarea rows={2} value={env} onChange={e => setEnv(e.target.value)} placeholder="API_KEY=…" spellCheck={false} /></label>
          <p className="hint">It starts inside the agent's own sandbox each time it runs (<code>npx</code> and <code>uvx</code> are there), so its tools
            show up once it has run.</p>
        </>}
        {mode === 'paste' && <>
          <label>Your MCP config <span className="hint">a <code>.mcp.json</code> (Claude Code, or a plugin's), Claude Desktop or Cursor's
            <code> mcpServers</code>, VS Code's <code>servers</code>, or Codex's <code>config.toml</code></span>
            <textarea autoFocus rows={10} value={config} onChange={e => setConfig(e.target.value)} spellCheck={false}
              placeholder={'{\n  "mcpServers": {\n    "linear": { "type": "http", "url": "https://mcp.linear.app/mcp" }\n  }\n}'} required /></label>
          <p className="hint">Each server becomes its own app. Secrets in it are stored encrypted; <code>${'{'}VARS{'}'}</code> from your own machine
            need filling in afterwards.</p>
        </>}
        {mode === 'web' && <>
          <p className="hint">Any REST API, even one with no MCP server. Agents get one tool, <code>get</code>: Agent Town
            makes the GET request for them, under this URL only, and adds the header itself, so your key never reaches the agent.</p>
          <label>Base URL<input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://api.example.com/v1" required /></label>
          <label>Authorization header <span className="hint">optional, e.g. <code>Bearer sk-…</code>. Stored encrypted, never shown again</span>
            <input value={auth} onChange={e => setAuth(e.target.value)} type="password" autoComplete="off" /></label>
        </>}
        <Err error={error} />
        <button className="primary" disabled={busy}>{busy ? 'Connecting…' : mode === 'paste' ? 'Import' : 'Connect'}</button>
      </form>
    </Modal>
  )
}
