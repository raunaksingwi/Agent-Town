// "+ Add": drop in a folder or some .md files; we work out which are agents and which are knowledge,
// show it in plain words, and add it all in one click.

import { usePlain } from './look'
import { useEffect, useState } from 'react'
import { seedOf } from './city/layout'
import { api, type ImportFile, type ImportPlan, type MarketAgent } from './api'
import { Avatar } from './avatar'
import { Err, LinkButton, Modal, msg } from './ui'

const TEXT = /\.(md|markdown|txt)$/i
const MAX = 200_000                 // one file (the server's limit too)
const MAX_TOTAL = 20_000_000        // everything in one go: more than any agents folder, less than a whole repo of notes
const MAX_FILES = 500
const JUNK = /(^|\/)(node_modules|\.git|__pycache__|\.venv|dist|build)(\/|$)/

type Picked = { files: ImportFile[]; other: number; problem?: string }

async function read(items: { file: File; path: string }[]): Promise<Picked> {
  const files: ImportFile[] = []
  let other = 0, total = 0
  for (const { file, path } of items) {
    if (JUNK.test(path)) continue
    if (!TEXT.test(path) || file.size > MAX) { other++; continue }
    total += file.size
    if (files.length >= MAX_FILES || total > MAX_TOTAL)
      return { files, other, problem: `That's more than Agent Town takes in one go (${MAX_FILES} files, ${MAX_TOTAL / 1_000_000} MB). Pick a smaller folder: the agents' own, not a whole repository.` }
    files.push({ path: path.replace(/^\//, ''), content: await file.text() })
  }
  return { files, other }
}

const fromInput = (list: FileList | null) =>
  read([...(list ?? [])].map(file => ({ file, path: file.webkitRelativePath || file.name })))

// A dropped folder arrives as a tree of entries, not a file list.
async function fromDrop(dt: DataTransfer): Promise<Picked> {
  const out: { file: File; path: string }[] = []
  const walk = async (e: FileSystemEntry): Promise<void> => {
    if (e.isFile) {
      const file = await new Promise<File>((res, rej) => (e as FileSystemFileEntry).file(res, rej))
      out.push({ file, path: e.fullPath })
    } else if (e.isDirectory && !JUNK.test(e.fullPath)) {
      const reader = (e as FileSystemDirectoryEntry).createReader()
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej))
        if (!batch.length) break
        for (const child of batch) await walk(child)
      }
    }
  }
  const roots = [...dt.items].map(i => i.webkitGetAsEntry()).filter((e): e is FileSystemEntry => !!e)
  for (const r of roots) await walk(r)
  return read(out)
}

export function AddModal({ onClose, onDone, onWrite }: { onClose: () => void; onDone: (firstId: number | null) => void; onWrite: () => void }) {
  const [picked, setPicked] = useState<Picked | null>(null)
  const [plan, setPlan] = useState<ImportPlan | null>(null)
  const [agentsOn, setAgentsOn] = useState<Set<string>>(new Set())
  const [sharedOn, setSharedOn] = useState<Set<string>>(new Set())
  const [main, setMain] = useState('')
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function analyse(p: Picked, mainFile?: string, picks: Record<string, string> = choices) {
    setError(null)
    if (p.problem) { setError(p.problem); return }
    if (!p.files.length) { setError('No .md or .txt files in there. Agents are written as markdown files.'); return }
    setBusy(true)
    try {
      const pl = await api.previewImport(p.files, mainFile, picks)
      setPicked(p); setPlan(pl)
      setAgentsOn(new Set(pl.agents.map(a => a.source)))
      setSharedOn(new Set(pl.shared.map(s => s.source)))
      setMain(pl.candidates[0] ?? '')
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }

  async function add() {
    if (!picked || !plan) return
    setBusy(true); setError(null)
    try {
      const r = await api.doImport({
        files: picked.files,
        agents: plan.agents.filter(a => agentsOn.has(a.source)).map(a => ({ source: a.source, name: a.name, files: a.files.map(f => f.source),
          team: a.team.filter(n => plan.agents.some(o => o.name === n && agentsOn.has(o.source))) })),
        shared: plan.shared.filter(s => sharedOn.has(s.source)).map(s => s.source),
      })
      onDone(r.created[0]?.id ?? r.updated[0]?.id ?? null)
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, key: string) => {
    const next = new Set(set)
    if (next.has(key)) next.delete(key); else next.add(key)
    setter(next)
  }

  // ---- 1. pick
  if (!plan) return (
    <Modal title="Add your agents" onClose={onClose} wide>
      <p className="hint">An agent is written down as one or more markdown (.md) files: what it should do, and what it should know.
        Bring a single file, a few, or a whole folder (like a <code>.claude</code> folder or an agents repo). We'll sort out the rest.</p>
      <div className={`drop${drag ? ' on' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={async e => { e.preventDefault(); setDrag(false); analyse(await fromDrop(e.dataTransfer)) }}>
        <b>{busy ? 'Reading…' : 'Drop a folder or files here'}</b>
        <div className="row center">
          <label className="button primary">Choose a folder
            <input type="file" hidden {...{ webkitdirectory: '' }} onChange={async e => analyse(await fromInput(e.target.files))} /></label>
          <label className="button">Choose files
            <input type="file" hidden multiple accept=".md,.markdown,.txt" onChange={async e => analyse(await fromInput(e.target.files))} /></label>
        </div>
        <span className="hint">Only text files are read. Nothing is saved until you confirm.</span>
      </div>
      <Err error={error} />
      <Market onDone={onDone} />
      <p className="switch">Starting from nothing? <LinkButton onClick={onWrite}>Write a new agent</LinkButton></p>
    </Modal>
  )

  // ---- 2a. no agent definition: which file is the agent?
  if (plan.needs_main) return (
    <Modal title="Which file is your agent?" onClose={onClose}>
      <p className="hint">These files don't say which one is the agent. Pick the one that describes what it should do;
        the other {plan.candidates.length - 1} become what it knows.</p>
      <select value={main} onChange={e => setMain(e.target.value)}>{plan.candidates.map(c => <option key={c}>{c}</option>)}</select>
      <Err error={error} />
      <div className="row"><button className="primary" disabled={busy || !main} onClick={() => analyse(picked!, main)}>Use this one</button>
        <button onClick={() => setPlan(null)}>Back</button></div>
    </Modal>
  )

  // ---- 2b. review
  const nA = plan.agents.filter(a => agentsOn.has(a.source)).length
  const nS = plan.shared.filter(s => sharedOn.has(s.source)).length
  const left = (picked?.other ?? 0) + plan.skipped.length
  return (
    <Modal title={`Found ${plan.agents.length} agent${plan.agents.length === 1 ? '' : 's'}`} onClose={onClose} wide>
      <p className="hint">Each becomes a building in your private district. Untick anything you don't want.</p>
      <ul className="list import">
        {plan.agents.map(a => (
          <li key={a.source}>
            <Avatar agent={{ slug: a.name, name: a.name, description: a.description, color: guessColor(a.name) }} size={40} />
            <label className="grow"><input type="checkbox" checked={agentsOn.has(a.source)} onChange={() => toggle(agentsOn, setAgentsOn, a.source)} />
              <b>{a.name}</b>{a.exists && <span className="mini">updates yours</span>}
              {a.description && <div className="meta wrap">{a.description}</div>}
              {a.team.length > 0 && <div className="meta wrap">👥 team: {a.team.join(', ')}</div>}</label>
            {a.alternatives.length > 1 && <select title="Which file holds its instructions" value={a.source} onClick={e => e.stopPropagation()}
              onChange={e => { const next = { ...choices, [a.name]: e.target.value }; setChoices(next); analyse(picked!, undefined, next) }}>
              {a.alternatives.map(x => <option key={x.source} value={x.source}>{x.kind === 'command' ? `/${a.name} command` : 'agent file'} · {x.lines} ln</option>)}
            </select>}
            <span className="meta" title={a.files.map(f => f.path).join('\n')}>
              {a.files.length ? `+ ${a.files.length} file${a.files.length === 1 ? '' : 's'} it uses` : ''}</span>
          </li>))}
      </ul>
      {plan.shared.length > 0 && <details className="shared-pick">
        <summary><b>{nS} shared file{nS === 1 ? '' : 's'}</b> <span className="hint">that all your agents can read (stored once, kept private)</span></summary>
        <ul className="list">{plan.shared.map(s => (
          <li key={s.source}><label className="grow"><input type="checkbox" checked={sharedOn.has(s.source)}
            onChange={() => toggle(sharedOn, setSharedOn, s.source)} /> {s.path}</label></li>))}</ul>
      </details>}
      {left > 0 && <p className="hint">Left out {left} file{left === 1 ? '' : 's'}: images, sounds, code, and anything in hidden folders.</p>}
      <Err error={error} />
      <div className="row">
        <button className="primary" disabled={busy || (!nA && !nS)} onClick={add}>
          {busy ? 'Adding…' : `Add ${nA} agent${nA === 1 ? '' : 's'}${nS ? ` and ${nS} shared file${nS === 1 ? '' : 's'}` : ''}`}</button>
        <button onClick={() => { setPlan(null); setPicked(null) }}>Start over</button>
      </div>
    </Modal>
  )
}

// Its colour isn't picked until it's added (backend/app/routers/agents.py), so preview one from its name.
const COLORS = ['#8a6fd1', '#d1694f', '#3f8fd2', '#4fae6a', '#d6a23a', '#c8579b', '#3aa6a6', '#7f8a99']
const guessColor = (name: string) => COLORS[seedOf(name) % COLORS.length]

// Ready-made agents from agents/ in the repo, added with one click.
function Market({ onDone }: { onDone: (firstId: number | null) => void }) {
  const [items, setItems] = useState<MarketAgent[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.market().then(setItems, () => setItems([])) }, [])
  const home = usePlain() ? 'office' : 'town'
  if (!items?.length) return null
  return (
    <section className="market">
      <h3>Or pick one from the agent market</h3>
      <div className="market-grid">{items.map(m => (
        <div key={m.slug} className="market-card">
          <div className="market-top"><Avatar agent={{ ...m, color: m.color || '#8a6fd1' }} size={40} /><b>{m.name}</b></div>
          <p>{m.description}</p>
          <div className="meta wrap">{m.tags.join(' · ')}{m.tools.length > 0 && <> · works with {m.tools.join(', ')}</>}</div>
          {m.team.length > 0 && <div className="meta wrap">👥 comes with its team: {m.team.join(', ')}</div>}
          {m.installed
            ? <button disabled title={`Already in your ${home}. Importing the same agent again (+ Add agents → your own files) updates it.`}>In your {home}</button>
            : <button className="primary" disabled={busy !== null} onClick={async () => {
              setBusy(m.slug); setError(null)
              try { const r = await api.installMarket(m.slug); onDone(r.agent.id) } catch (e) { setError(msg(e)) } finally { setBusy(null) }
            }}>{busy === m.slug ? 'Adding…' : 'Add'}</button>}
        </div>))}
      </div>
      <Err error={error} />
      <p className="hint">Don't see the one you need? Ask your mayor to make it with you.</p>
    </section>
  )
}
