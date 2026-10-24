// The card at the bottom of the screen: whatever you clicked in the city.

import { useEffect, useState } from 'react'
import { api, type Connection, type FileFull, type MyAgent, type Share, type SharedFile, type Thinking } from './api'
import { STATUS_LABEL } from './city/layout'
import { pairs, signIn } from './connectors'
import { useCredentials } from './hooks'
import { ago } from './time'
import { Err, LinkButton, Md, Modal, msg, readFiles } from './ui'

type Reload = () => Promise<void>

export function FileModal({ file, editable, onClose, onSave }: { file: FileFull; editable: boolean; onClose: () => void; onSave?: (content: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(file.content)
  const [error, setError] = useState<string | null>(null)
  return (
    <Modal title={file.path} onClose={onClose} wide>
      <p className="hint">{file.lines} lines · {file.bytes.toLocaleString()} bytes</p>
      {editing ? <>
        <textarea className="editor" value={text} onChange={e => setText(e.target.value)} rows={20} spellCheck={false} />
        <Err error={error} />
        <div className="row"><button className="primary" onClick={async () => {
          try { await onSave!(text); setEditing(false) } catch (e) { setError(msg(e)) }
        }}>Save</button><button onClick={() => { setEditing(false); setText(file.content) }}>Cancel</button></div>
      </> : <>
        <Md text={file.content} />
        {editable && <button onClick={() => setEditing(true)}>Edit</button>}
      </>}
    </Modal>
  )
}

export function ManifestModal({ agentId, onClose }: { agentId: number; onClose: () => void }) {
  const [data, setData] = useState<string>('Loading…')
  useEffect(() => { api.manifest(agentId).then(m => setData(JSON.stringify(m, null, 2)), e => setData(msg(e))) }, [agentId])
  return (
    <Modal title="Manifest" onClose={onClose} wide>
      <p className="hint">What this agent is handed when it runs: its instructions, files, the tools it may use, and the public
        items it can read. Its sandbox starts from exactly this. Credentials are never in it: the sandbox
        fetches them separately, with a token that only works for that one run.</p>
      <pre className="json">{data}</pre>
    </Modal>
  )
}

// ---------- an MCP connection ----------
export function StationCard({ conn, reload, onClose }: { conn: Connection; reload: Reload; onClose: () => void }) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [auth, setAuth] = useState('')
  const [secrets, setSecrets] = useState<string | null>(null)   // replacing its headers or environment
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await fn(); await reload() } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }
  const stdio = conn.transport === 'stdio'
  const names = stdio ? conn.env_names : conn.header_names
  return (
    <div className="card">
      <button className="x" onClick={onClose} aria-label="Close">×</button>
      <h2><span className={`dot big ${conn.status}`} />{conn.name}<span className="pill">{STATUS_LABEL[conn.status]}</span></h2>
      <p className="tag mono">{conn.transport === 'stdio' ? `$ ${conn.command}` : conn.url}</p>
      <p className="hint">{conn.status_detail} · checked {ago(conn.last_checked_at)}
        {conn.server_name && <> · server <b>{conn.server_name}</b> {conn.server_version}</>}
        {conn.has_auth && <> · credentials stored</>}
        {conn.sign_in === 'signed_in' && <> · signed in</>}</p>
      {conn.transport === 'http' && conn.sign_in !== 'none' && <div className="row">
        {conn.status === 'auth_required' || conn.sign_in === 'available'
          ? <button className="primary" onClick={() => signIn(conn)}>Sign in{conn.sign_in === 'signed_in' ? ' again' : ''}</button>
          : <button disabled={busy} onClick={() => run(() => api.signOutConnection(conn.id))}>Sign out</button>}
        <span className="hint">{conn.own_client ? 'Signs in with your own OAuth client.' : 'Signs in with the app itself, like a Claude connector.'}</span>
      </div>}
      <div className="cols">
        <section>
          <h3>Tools · {conn.tools.length}</h3>
          {conn.tools.length ? <ul className="list">{conn.tools.map(t => (
            <li key={t.name}><span className="grow"><b className="mono">{t.name}</b><div className="meta wrap">{t.description}</div></span></li>))}</ul>
            : <p className="empty">{conn.transport === 'stdio' ? 'Listed once it runs in a sandbox.' : 'None listed yet.'}</p>}
        </section>
        <section>
          <h3>Used by</h3>
          {conn.granted_to.length ? <ul className="list">{conn.granted_to.map((g, i) => (
            <li key={i}><span className="grow">{g.agent}</span><span className="meta">{g.tool_name ?? 'all tools'}</span></li>))}</ul>
            : <p className="empty">No agent yet. Open an agent and tick this tool.</p>}
          {conn.transport === 'web' && <div className="row">
            <input className="note" type="password" placeholder={conn.has_auth ? 'Replace Authorization header' : 'Authorization header (e.g. Bearer …)'}
              value={auth} onChange={e => setAuth(e.target.value)} autoComplete="off" />
            <button disabled={!auth || busy} onClick={() => run(async () => { await api.updateConnection(conn.id, { auth_header: auth }); setAuth('') })}>Save</button>
          </div>}
          {(conn.transport === 'http' || stdio) && <>
            <h3>{stdio ? 'Environment' : 'Headers'}</h3>
            <p className="hint">{names.length ? <>Stored encrypted: <code>{names.join(', ')}</code></> : 'None.'}{' '}
              {secrets === null && <LinkButton onClick={() => setSecrets('')}>{names.length ? 'Replace' : 'Add'}</LinkButton>}</p>
            {secrets !== null && <div className="form">
              <textarea rows={3} value={secrets} onChange={e => setSecrets(e.target.value)} spellCheck={false}
                placeholder={stdio ? 'API_KEY=…' : 'Authorization: Bearer …'} />
              <div className="row tight">
                <button className="primary" disabled={busy} onClick={() => run(async () => {
                  const v = pairs(secrets, stdio ? '=' : ':')
                  await api.updateConnection(conn.id, stdio ? { env: v } : { headers: v })
                  setSecrets(null)
                })}>Save</button>
                <button onClick={() => setSecrets(null)}>Cancel</button>
                <span className="hint">Replaces all of them. Save it empty to remove them.</span>
              </div>
            </div>}
          </>}
        </section>
      </div>
      <div className="row">
        <button className="primary" disabled={busy} onClick={() => run(() => api.checkConnection(conn.id))}>{busy ? 'Checking…' : 'Check again'}</button>
        <span className="grow" />
        <button className="danger" onClick={() => { if (confirm(`Remove ${conn.name}?`)) run(async () => { await api.deleteConnection(conn.id); onClose() }) }}>Remove</button>
      </div>
      <Err error={error} />
    </div>
  )
}

// ---------- the public district ----------
export function SharedAgentCard({ share, onClose }: { share: Share; onClose: () => void }) {
  const [full, setFull] = useState<Share | null>(null)
  const [open, setOpen] = useState<FileFull | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.getShare(share.id).then(setFull, e => setError(msg(e))) }, [share.id])
  const a = (full ?? share).agent!
  return (
    <div className="card">
      <button className="x" onClick={onClose} aria-label="Close">×</button>
      <h2><span className="sw" style={{ background: a.color }} />{a.name}<span className="pill">by @{share.owner}</span></h2>
      {a.description && <p className="tag">{a.description}</p>}
      {share.note && <p className="note-box">“{share.note}”</p>}
      <p className="hint">{share.allow_agent_use ? 'Other people’s agents can read and consult it.' : 'Readable by people; not offered to other agents.'}</p>
      <h3>Floors · {a.files.length} files · {a.lines} lines</h3>
      <ul className="list">{a.files.map(f => (
        <li key={f.id}>{'content' in f
          ? <button className="rowbtn grow" onClick={() => setOpen(f as FileFull)}><span className="grow">{f.path}</span><span className="meta">{f.lines} ln</span></button>
          : <><span className="grow">{f.path}</span><span className="meta">{f.lines} ln</span></>}</li>))}</ul>
      <Err error={error} />
      {open && <FileModal file={open} editable={false} onClose={() => setOpen(null)} />}
    </div>
  )
}

export function LibraryCard({ shares, me, reload, onClose }: { shares: Share[]; me: string | null; reload: Reload; onClose: () => void }) {
  const [open, setOpen] = useState<FileFull | null>(null)
  const [error, setError] = useState<string | null>(null)
  const read = async (s: Share) => { try { const full = await api.getShare(s.id); setOpen(full.file as FileFull) } catch (e) { setError(msg(e)) } }
  const unshare = async (s: Share) => { try { await api.unshare(s.id); await reload() } catch (e) { setError(msg(e)) } }
  return (
    <div className="card">
      <button className="x" onClick={onClose} aria-label="Close">×</button>
      <h2>📚 Library<span className="pill">{shares.length} shared files</span></h2>
      <p className="tag">Knowledge people shared from their agents. Agents that may read the public district get these.</p>
      <ul className="list">{shares.map(s => (
        <li key={s.id}>
          <button className="rowbtn grow" onClick={() => read(s)}>
            <span className="grow">{s.title}<div className="meta">@{s.owner} · from {s.file && 'agent' in s.file ? s.file.agent : ''}{s.note ? ` · ${s.note}` : ''}</div></span>
            <span className="meta">{s.file?.lines} ln</span></button>
          {me === s.owner && <button className="tiny" onClick={() => unshare(s)}>unshare</button>}
        </li>))}</ul>
      <Err error={error} />
      {open && <FileModal file={open} editable={false} onClose={() => setOpen(null)} />}
    </div>
  )
}

// Which brain an agent thinks with, and how hard. Each agent has its own: a quick helper on Haiku, a
// careful planner on Opus thinking at max. Changes apply from its next chat.
const CLAUDE_MODELS: { id: string; name: string; says: string }[] = [
  { id: 'claude-haiku-5-5', name: 'Haiku 5.5', says: 'fastest and cheapest, for quick everyday jobs' },
  { id: 'claude-sonnet-5-5', name: 'Sonnet 5.5', says: 'fast and capable, a good all-rounder' },
  { id: 'claude-opus-5-5', name: 'Opus 5.5', says: 'smarter, for harder work' },
  { id: 'claude-fable-5-1', name: 'Fable 5.1', says: 'the most capable, slower and pricier' },
]
const THINKING: { id: Thinking; name: string; says: string }[] = [
  { id: '', name: 'Auto', says: "the model's own default" },
  { id: 'low', name: 'Quick', says: 'answers fast, thinks briefly' },
  { id: 'medium', name: 'Balanced', says: 'thinks a little before answering' },
  { id: 'high', name: 'Careful', says: 'thinks things through' },
  { id: 'xhigh', name: 'Deep', says: 'works hard on tricky jobs' },
  { id: 'max', name: 'Deepest', says: 'as hard as it can: slowest, uses the most of your plan' },
]

export function BrainPicker({ agent, run }: { agent: MyAgent; run: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { creds } = useCredentials()
  const [model, setModel] = useState(agent.model)
  if (creds === null) return null
  if (!creds.length) return <p className="empty">No AI account yet. Add your Claude or ChatGPT account in Settings (under your name, top right) → Account and AI models.</p>
  const def = creds.find(c => c.is_default)
  const cred = creds.find(c => c.id === agent.model_credential_id) ?? def
  const claude = !cred || cred.provider === 'anthropic'
  const known = CLAUDE_MODELS.some(m => m.id === agent.model)
  const think = THINKING.find(t => t.id === agent.thinking) ?? THINKING[0]
  return (
    <div className="brain">
      {creds.length > 1 && <label>Account
        <select value={agent.model_credential_id ?? 0}
          onChange={e => run(() => api.updateAgent(agent.id, { model_credential_id: Number(e.target.value), model: '' }))}>
          <option value={0}>Your default{def ? ` (${def.label})` : ''}</option>
          {creds.map(c => <option key={c.id} value={c.id}>{c.label}{c.hint ? ` …${c.hint}` : ''}</option>)}
        </select></label>}
      <label>Brain
        {claude
          ? <select value={agent.model} onChange={e => run(() => api.updateAgent(agent.id, { model: e.target.value }))}>
              <option value="">Automatic (Sonnet 5.5)</option>
              {CLAUDE_MODELS.map(m => <option key={m.id} value={m.id}>{m.name}: {m.says}</option>)}
              {agent.model && !known && <option value={agent.model}>{agent.model}</option>}
            </select>
          : <input value={model} placeholder="Automatic (Codex's default model)" onChange={e => setModel(e.target.value)}
              onBlur={() => model !== agent.model && run(() => api.updateAgent(agent.id, { model: model.trim() }))} />}
      </label>
      <label>Thinking
        <span className="seg wrap" role="radiogroup" aria-label="How hard it thinks">
          {THINKING.map(t => <button key={t.id} type="button" role="radio" aria-checked={t.id === think.id} title={t.says}
            className={t.id === think.id ? 'on' : ''} onClick={() => t.id !== think.id && run(() => api.updateAgent(agent.id, { thinking: t.id }))}>{t.name}</button>)}
        </span>
        <span className="hint">{think.name}: {think.says}. More thinking is smarter but slower{claude ? '' : ' (Codex tops out at Deep)'}.</span>
      </label>
    </div>
  )
}

// ---------- your shared files ----------
/** `onProfile` opens About you, the easiest first shared file (about-us.md), offered while there are none. */
export function SharedFilesCard({ files, reload, onClose, onProfile }: { files: SharedFile[]; reload: Reload; onClose: () => void; onProfile?: () => void }) {
  const [open, setOpen] = useState<FileFull | null>(null)
  const [error, setError] = useState<string | null>(null)
  const run = async (fn: () => Promise<unknown>) => {
    setError(null)
    try { await fn(); await reload() } catch (e) { setError(msg(e)) }
  }
  return (
    <div className="card">
      <button className="x" onClick={onClose} aria-label="Close">×</button>
      <h2>🗂 Shared files<span className="pill">private · {files.length} files</span></h2>
      <p className="tag">Knowledge every one of your agents can read: put things several agents need here once, like "about us" or a style guide.</p>
      {files.length === 0 && <p className="empty">Nothing here yet.{onProfile && <> <button className="linklike" onClick={onProfile}>Tell your agents about you</button> and it's saved here as <code>about-us.md</code>.</>}</p>}
      <ul className="list">{files.map(f => (
        <li key={f.id}>
          <button className="rowbtn grow" onClick={() => run(async () => { const full = await api.sharedFile(f.id); setOpen({ ...full, content: full.content }) })}>
            <span className="grow">{f.path}</span><span className="meta">{f.lines} ln</span></button>
          <button className="tiny" title={`Delete ${f.path}`} aria-label={`Delete ${f.path}`} onClick={() => { if (confirm(`Delete ${f.path}?`)) run(() => api.deleteSharedFile(f.id)) }}>✕</button>
        </li>))}</ul>
      <label className="linklike">+ add files
        <input type="file" multiple accept=".md,.txt" hidden onChange={async e => {
          const picked = await readFiles(e.target.files)
          run(async () => { for (const f of picked) await api.putSharedFile(f.path, f.content) })
        }} /></label>
      <Err error={error} />
      {open && <FileModal file={open} editable onClose={() => setOpen(null)}
        onSave={async content => { await api.putSharedFile(open.path, content); await reload(); setOpen(null) }} />}
    </div>
  )
}
