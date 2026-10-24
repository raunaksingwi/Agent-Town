// "Connect your AI": the one step every town needs before an agent can think. Most people bring the
// plan they already pay for, so that comes first: Claude by `claude setup-token` (Anthropic doesn't let
// other apps sign in to a Claude plan), ChatGPT by a one-time code on OpenAI's page (codex_login.py).
// An API key is one link away. We work out what was pasted, check it, and say plainly if it failed.
// The account screen (account.tsx) stays for managing several accounts.

import { useEffect, useState, type ReactNode } from 'react'
import { api, type CredKind, type Provider } from './api'
import { invalidateCredentials, useCredentials } from './hooks'
import { Err, LinkButton, Modal, msg } from './ui'

type Pick = 'claude' | 'chatgpt'
type Device = { handle: string; code: string; url: string; interval: number }

/** What a pasted secret is, from its shape. The server checks the same shapes (model_check.py). */
export function detect(secret: string): { provider: Provider; kind: CredKind; says: string } | null {
  const s = secret.trim()
  if (s.startsWith('sk-ant-api')) return { provider: 'anthropic', kind: 'api_key', says: 'a Claude API key' }
  if (s.startsWith('sk-ant-oat')) return { provider: 'anthropic', kind: 'subscription', says: 'a Claude subscription token' }
  if (s.startsWith('{') && s.includes('tokens')) return { provider: 'openai', kind: 'subscription', says: 'a ChatGPT (Codex) sign-in' }
  if (/^sk-[A-Za-z0-9_-]{20,}$/.test(s)) return { provider: 'openai', kind: 'api_key', says: 'an OpenAI API key' }
  return null
}

const KEYS: Record<Pick, { company: string; url: string; how: string }> = {
  claude: { company: 'Anthropic', url: 'https://console.anthropic.com/settings/keys', how: 'Sign in, add a few dollars under Billing, then Create key.' },
  chatgpt: { company: 'OpenAI', url: 'https://platform.openai.com/api-keys', how: 'Sign in, add a few dollars under Billing, then Create new secret key.' },
}
const NAME: Record<Pick, string> = { claude: 'Claude', chatgpt: 'ChatGPT' }

export function ConnectAiModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [pick, setPick] = useState<Pick | null>(null)
  const [recommended, setRecommended] = useState(false)
  const [useKey, setUseKey] = useState(false)          // the API key instead of a plan
  const [pasteAuth, setPasteAuth] = useState(false)    // ChatGPT: paste auth.json instead of signing in
  const [secret, setSecret] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const { subs } = useCredentials()                    // does this server take subscriptions?
  const key = useKey || !subs

  const what = detect(secret)
  const blockedSub = what?.kind === 'subscription' && !subs

  async function connect() {
    if (!what) return
    setBusy(true); setError(null)
    try {
      const c = await api.addCredential({ provider: what.provider, kind: what.kind, secret: secret.trim() })
      if (c.status === 'invalid') {
        await api.deleteCredential(c.id).catch(() => {})
        const company = what.provider === 'anthropic' ? 'Anthropic' : 'OpenAI'
        setError(`${company} didn't accept that key. Copy the whole thing and try again.`)
        return
      }
      invalidateCredentials()
      setDone(c.status === 'error'
        ? 'Saved, but we couldn\'t check it yet. If your first chat fails, add it again.'
        : what.kind === 'subscription' ? 'Saved. It\'s checked on first use.' : 'It works.')
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }

  if (done) return (
    <Modal title="You're connected" onClose={onDone}>
      <p className="connect-done">✓ Your agents can think now. {done}</p>
      <p className="hint">Stored encrypted, used only by your agents. Manage it under your name → Account and AI models.</p>
      <div className="row"><span className="grow" /><button className="primary" autoFocus onClick={onDone}>Start talking</button></div>
    </Modal>
  )

  if (!pick) return (
    <Modal title="Connect your AI" onClose={onClose} wide>
      <p className="hint">Your agents think with your Claude or ChatGPT plan. Do it once for all of them.</p>
      <div className="welcome-choices three">
        <button className="welcome-choice primary-choice" onClick={() => setPick('claude')}>
          <b>Claude</b><span>Recommended. Maya can hand work to her team.</span></button>
        <button className="welcome-choice" onClick={() => setPick('chatgpt')}>
          <b>ChatGPT</b><span>Works, but agents can't hand off work yet.</span></button>
        <button className="welcome-choice" onClick={() => { setRecommended(true); setPick('claude') }}>
          <b>Neither yet</b><span>We'll help you get Claude.</span></button>
      </div>
    </Modal>
  )

  const k = KEYS[pick], name = NAME[pick]
  const back = () => { setPick(null); setRecommended(false); setUseKey(false); setPasteAuth(false); setSecret(''); setError(null) }
  const paste = (label: string, placeholder: string) => <>
    <label className="paste">{label}
      <input type="password" autoComplete="off" spellCheck={false} placeholder={placeholder}
        value={secret} onChange={e => { setSecret(e.target.value); setError(null) }}
        onKeyDown={e => { if (e.key === 'Enter' && what && !blockedSub) connect() }} />
    </label>
    {secret.trim() && <p className={`hint detect ${what && !blockedSub ? 'ok' : 'bad'}`}>
      {!what ? 'Doesn\'t look like a key or token yet. Copy the whole thing.'
        : blockedSub ? 'This server doesn\'t take subscriptions. Use an API key.'
        : `✓ That's ${what.says}.`}</p>}
  </>
  const showConnect = key || pick === 'claude' || pasteAuth

  return (
    <Modal title={`Connect ${name}`} onClose={onClose} wide>
      {recommended && !key && <p className="hint">No plan yet? Get Claude Pro at <a href="https://claude.ai/upgrade" target="_blank" rel="noreferrer">claude.ai</a>,
        then come back. Or <LinkButton onClick={() => setUseKey(true)}>pay as you go with an API key</LinkButton>.</p>}

      {key && <>
        <p className="hint">{k.how} Billed by {k.company}, separate from a {name} plan.</p>
        <p><a className="button primary" href={k.url} target="_blank" rel="noreferrer">Get a key ↗</a></p>
        {paste('API key', pick === 'claude' ? 'sk-ant-api…' : 'sk-…')}
      </>}

      {!key && pick === 'claude' && <>
        <p className="hint">In a terminal, run this, sign in, and paste the token it prints.</p>
        <Command text="claude setup-token" />
        <p className="hint">No Claude Code? <Command text="npm install -g @anthropic-ai/claude-code" inline /> first.</p>
        {paste('Token', 'sk-ant-oat…')}
      </>}

      {!key && pick === 'chatgpt' && !pasteAuth &&
        <ChatGptSignIn onDone={() => setDone(`Signed in with ChatGPT. It's checked on first use.`)} onError={setError}>
          <p className="hint">Already use Codex? <LinkButton onClick={() => setPasteAuth(true)}>Paste ~/.codex/auth.json</LinkButton> instead.</p>
        </ChatGptSignIn>}
      {!key && pick === 'chatgpt' && pasteAuth && <>
        <p className="hint">Run <code>codex login</code>, then paste everything in <code>~/.codex/auth.json</code>.</p>
        {paste('auth.json', '{ "tokens": … }')}
      </>}

      {!key && <p className="hint">Check your plan's terms for use outside {k.company}'s apps.</p>}
      {subs && <p className="switch"><LinkButton onClick={() => { setUseKey(!useKey); setSecret(''); setError(null) }}>
        {useKey ? `Use my ${name} plan instead` : 'Use an API key instead'}</LinkButton></p>}
      <Err error={error} />
      <div className="row">
        <button onClick={back}>Back</button>
        <span className="grow" />
        {showConnect && <button className="primary" disabled={busy || !what || blockedSub} onClick={connect}>{busy ? 'Checking…' : 'Connect'}</button>}
      </div>
    </Modal>
  )
}

/** Sign in with ChatGPT: a one-time code the user approves on OpenAI's page, then the server saves the
 *  login (codex_login.py). `children` shows under the button until the sign-in starts. */
export function ChatGptSignIn({ onDone, onError, children }: { onDone: () => void; onError: (e: string | null) => void; children?: ReactNode }) {
  const [device, setDevice] = useState<Device | null>(null)
  const [busy, setBusy] = useState(false)

  // ask the server every few seconds whether the code was approved on OpenAI's page
  useEffect(() => {
    if (!device) return
    let stop = false
    const t = setInterval(async () => {
      try {
        const r = await api.chatgptPoll(device.handle)
        if (stop || r.pending) return
        stop = true; clearInterval(t); invalidateCredentials(); setDevice(null); onDone()
      } catch (e) { stop = true; clearInterval(t); setDevice(null); onError(msg(e)) }
    }, device.interval * 1000)
    return () => { stop = true; clearInterval(t) }
  }, [device])

  async function start() {
    setBusy(true); onError(null)
    try { setDevice(await api.chatgptStart()) } catch (e) { onError(msg(e)) } finally { setBusy(false) }
  }

  if (device) return (
    <div className="device">
      <p className="hint">Open OpenAI, sign in, and enter this code:</p>
      <p className="device-code">{device.code}</p>
      <p><a className="button primary" href={device.url} target="_blank" rel="noreferrer">Open OpenAI ↗</a></p>
      <p className="hint">Waiting for you to approve… This finishes on its own.</p>
    </div>
  )
  return <>
    <p className="hint">Sign in on OpenAI's page with a one-time code. No terminal needed.</p>
    <p><button type="button" className="primary" disabled={busy} onClick={start}>{busy ? 'Starting…' : 'Sign in with ChatGPT'}</button></p>
    {children}
  </>
}

/** A command to run, with a Copy button. */
function Command({ text, inline }: { text: string; inline?: boolean }) {
  const [copied, setCopied] = useState(false)
  const copy = () => { navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }, () => {}) }
  return <span className={`command${inline ? ' inline' : ''}`}><code>{text}</code>
    <button type="button" className="linklike" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button></span>
}
