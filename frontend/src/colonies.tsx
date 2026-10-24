// Colonies: a lead and the agents it hands work to (its team). Each colony is one block in the town.
// Here you see them, make more, rename or delete one. A colony can start empty (just a name) and get its agents later:
// until it has a lead and a team it's kept on your account (City.empty_colonies), not on an agent. The server moves it
// over the moment a lead takes its name (town.name_colony), whichever screen or tool does it, so nothing here has to.
// The mayor can propose them too (its agent-builder skill, backend/app/town.py).

import { useTeamWord } from './look'
import { useEffect, useState } from 'react'
import { api, type City, type EmptyColony, type MarketAgent } from './api'
import { agentCount, coloniesOf, colonyName, leads, nice, type Colony } from './colony'
import { Err, LinkButton, Modal, msg } from './ui'

export function ColoniesModal({ city, reload, onClose, onVisit, onAddAgents }: {
  city: City; reload: () => Promise<void>; onClose: () => void
  onVisit: (agentId: number) => void; onAddAgents: () => void
}) {
  const { colonies, loners } = coloniesOf(city.agents)
  const empties = city.empty_colonies ?? []
  const w = useTeamWord()                                         // colonies, or cabins in the Office
  const [creating, setCreating] = useState(false)
  const [filling, setFilling] = useState<string | null>(null)     // the empty colony (by name) getting its agents
  const [renamingEmpty, setRenamingEmpty] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)   // the lead of the colony being deleted
  const [renaming, setRenaming] = useState<number | null>(null)   // …or being renamed
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function act(f: () => Promise<unknown>) {
    setBusy(true); setError(null)
    try { await f(); await reload(); setDeleting(null); setRenaming(null); setRenamingEmpty(null) } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }
  const saveEmpties = (list: EmptyColony[]) => api.setEmptyColonies(list)
  const takenNames = [...colonies.map(c => colonyName(c.lead, w.one)), ...empties.map(e => e.name)].map(n => n.toLowerCase())
  // the agents only this colony has: deleting them never takes an agent out of another colony
  const ownAgents = (c: Colony) => [c.lead, ...c.members.filter(m => !city.agents.some(o => o.id !== c.lead.id && o.team.includes(m.id)))]

  return (
    <Modal title={`Your ${w.many}`} onClose={onClose} wide>
      <p className="hint">A {w.one} is a team for one part of your work (Company, Outreach, Personal…): a lead you talk to,
        and the agents it hands work to, or just the lead on its own. Each one is {w.one === 'cabin' ? 'a cabin in your office' : 'a block in your town'}. Your assistant can set them up with you: just ask it.</p>

      {colonies.length === 0 && empties.length === 0 && <p className="empty">No {w.many} yet.</p>}
      <div className="colonies">
        {colonies.map(c => <div key={c.lead.id} className="colony">
          <span className="sw" style={{ background: c.lead.color }} />
          <div className="grow">
            {renaming === c.lead.id
              ? <ColonyFields name={c.lead.colony_name || colonyName(c.lead, w.one)} about={c.lead.colony_about} busy={busy}
                onCancel={() => setRenaming(null)}
                onSave={(colony_name, colony_about) => act(() => api.updateAgent(c.lead.id, { colony_name, colony_about }))} />
              : <>
                <div><b>{colonyName(c.lead, w.one)}</b> <span className="hint">· {agentCount(c.members.length + 1)}</span></div>
                <div className="colony-about">{c.lead.colony_about || <span className="hint">{c.lead.description}</span>}</div>
              </>}
            <div className="colony-agents"><span className="pill">{nice(c.lead.name)} · lead</span>
              {c.members.map(m => <span key={m.id} className="pill">{nice(m.name)}</span>)}</div>
            {deleting === c.lead.id && <div className="colony-del">
              <span>Delete {colonyName(c.lead, w.one)}?</span>
              <button disabled={busy} onClick={() => act(async () => { await api.setTeam(c.lead.id, []); await api.updateAgent(c.lead.id, { colony_name: '', colony_about: '' }) })}
                title={`The ${w.one} goes; its agents stay, without a team`}>Keep its agents</button>
              <button className="danger" disabled={busy} onClick={() => act(async () => { for (const a of ownAgents(c)) await api.deleteAgent(a.id) })}>
                Delete its {ownAgents(c).length} agents too</button>
              <button disabled={busy} onClick={() => setDeleting(null)}>Cancel</button>
            </div>}
          </div>
          {deleting !== c.lead.id && renaming !== c.lead.id && <>
            <button onClick={() => onVisit(c.lead.id)}>Visit</button>
            <button onClick={() => { setDeleting(null); setRenaming(c.lead.id) }}>Rename</button>
            <button onClick={() => { setRenaming(null); setDeleting(c.lead.id) }}>Delete</button>
          </>}
        </div>)}
        {empties.map(e => <div key={'empty:' + e.name} className="colony">
          <span className="sw" style={{ background: '#d9c49a' }} />
          <div className="grow">
            {renamingEmpty === e.name
              ? <ColonyFields name={e.name} about={e.about} busy={busy} onCancel={() => setRenamingEmpty(null)}
                onSave={(name, about) => act(() => saveEmpties(empties.map(x => x === e ? { name, about } : x)))} />
              : <>
                <div><b>{e.name}</b> <span className="hint">· no agents yet</span></div>
                {e.about && <div className="colony-about">{e.about}</div>}
              </>}
            {filling === e.name && <NewColony city={city} busy={busy} act={act} initial={e} taken={takenNames.filter(n => n !== e.name.toLowerCase())}
              onDone={() => setFilling(null)} onAddAgents={onAddAgents}
              onEmpty={ne => saveEmpties(empties.map(x => x === e ? ne : x))} />}
          </div>
          {renamingEmpty !== e.name && filling !== e.name && <>
            <button className="primary" onClick={() => { setRenamingEmpty(null); setCreating(false); setFilling(e.name) }}>Add agents</button>
            <button onClick={() => { setFilling(null); setRenamingEmpty(e.name) }}>Rename</button>
            <button disabled={busy} onClick={() => act(() => saveEmpties(empties.filter(x => x !== e)))}
              title="It has no agents, so nothing else goes">Delete</button>
          </>}
        </div>)}
      </div>

      {loners.length > 0 && <>
        <h3 className="colony-h">Not in a {w.one}</h3>
        <div className="colony-agents">{loners.map(a => <span key={a.id} className="pill">{nice(a.name)}</span>)}</div>
      </>}

      <Err error={error} />
      {creating
        ? <NewColony city={city} busy={busy} act={act} taken={takenNames} onDone={() => setCreating(false)} onAddAgents={onAddAgents}
          onEmpty={e => saveEmpties([...empties, e])} />
        : <div className="row">
          <button className="primary" onClick={() => { setFilling(null); setCreating(true) }}>+ New {w.one}</button>
        </div>}
    </Modal>
  )
}

/** A ready-made colony from the market, or one you put together from your own agents, or just a name for now
 *  (no lead picked: it's kept as an empty colony). With `initial`, it's an empty colony getting its agents. */
function NewColony({ city, busy, act, initial, taken, onDone, onAddAgents, onEmpty }: {
  city: City; busy: boolean; act: (f: () => Promise<unknown>) => Promise<void>; initial?: EmptyColony; taken: string[]
  onDone: () => void; onAddAgents: () => void
  onEmpty: (c: EmptyColony) => Promise<unknown>     // saved without agents
}) {
  const [market, setMarket] = useState<MarketAgent[] | null>(null)
  const w = useTeamWord()
  const [lead, setLead] = useState<number | ''>('')
  const [members, setMembers] = useState<number[]>([])
  const [name, setName] = useState(initial?.name ?? '')
  const [about, setAbout] = useState(initial?.about ?? '')
  useEffect(() => { if (!initial) api.market().then(setMarket, () => setMarket([])) }, [initial])
  const { leadOf } = coloniesOf(city.agents)
  const ready = (market ?? []).filter(m => m.team.length && !m.installed)

  // An agent belongs to one colony: joining this one takes it out of any other team. Several requests, the
  // additive ones first (name, then the lead's team) and taking agents out of other teams last, so if one fails
  // the colony exists and at worst an agent is in two teams for a moment; the error says what happened.
  // Naming the lead's colony like an empty one fills that one in (the server drops it from the list).
  async function create() {
    const moving = new Set([Number(lead), ...members])
    await api.updateAgent(Number(lead), { colony_name: name.trim(), colony_about: about.trim() })
    await api.setTeam(Number(lead), members)
    for (const m of city.agents.filter(a => members.includes(a.id) && leads(a)))   // a colony of one joining: no longer one
      await api.updateAgent(m.id, { colony_name: '', colony_about: '' })
    for (const other of city.agents.filter(a => a.id !== Number(lead) && a.team.some(id => moving.has(id))))
      await api.setTeam(other.id, other.team.filter(id => !moving.has(id)))
  }
  const dup = taken.includes(name.trim().toLowerCase())
  const empty = lead === ''

  return (
    <div className="form boxed">
      {!initial && <h3>New {w.one}</h3>}
      {ready.length > 0 && <>
        <span className="hint">Ready-made, from the agent market:</span>
        {ready.map(m => <div key={m.slug} className="colony">
          <span className="sw" style={{ background: m.color }} />
          <div className="grow"><b>{colonyName(m, w.one)}</b> <span className="hint">· {nice(m.name)} and {m.team.map(nice).join(', ')}</span>
            <div className="hint">{m.description}</div></div>
          <button className="primary" disabled={busy} onClick={() => act(async () => { await api.installMarket(m.slug); onDone() })}>Add</button>
        </div>)}
        <span className="hint">Or from your own agents:</span>
      </>}
      {!initial && <>
        <label>Name <span className="hint">e.g. Outreach, Product, Home</span>
          <input value={name} maxLength={60} onChange={e => setName(e.target.value)} placeholder="Outreach" /></label>
        {dup && <span className="hint">You already have a {w.one} called that.</span>}
        <label>What it's for <span className="hint">optional</span>
          <input value={about} maxLength={300} onChange={e => setAbout(e.target.value)} placeholder="Posts, newsletters and cold emails" /></label>
      </>}
      {city.agents.length === 0
        ? <p className="hint">{initial ? 'Its agents: a lead, and any it hands work to.' : 'You can create it empty and put agents in later.'}{' '}
          <LinkButton onClick={onAddAgents}>Add agents</LinkButton> to your town{initial ? ' first' : ''}.</p>
        : <>
          <label>Its lead <span className="hint">the one you talk to; it hands work to the rest{initial ? '' : '. Leave it for now to start empty'}</span>
            <select value={lead} onChange={e => { const v = e.target.value ? Number(e.target.value) : ''; setLead(v); setMembers(city.agents.find(a => a.id === v)?.team ?? []) }}>
              <option value="">{initial ? 'Pick an agent…' : 'None yet'}</option>
              {city.agents.map(a => <option key={a.id} value={a.id}>{nice(a.name)}{leads(a) ? ` (leads ${colonyName(a, w.one)})` : ''}</option>)}
            </select></label>
          {lead !== '' && <div className="colony-pick">
            <b>Its team</b> <span className="hint">optional: with none, it's a {w.one} of one</span>
            {city.agents.filter(a => a.id !== lead && !a.team.length).map(a => <label key={a.id}>
              <input type="checkbox" checked={members.includes(a.id)}
                onChange={e => setMembers(e.target.checked ? [...members, a.id] : members.filter(id => id !== a.id))} />
              {nice(a.name)}{leadOf.has(a.id) && leadOf.get(a.id)!.id !== lead && <span className="hint"> · moves here from {colonyName(leadOf.get(a.id)!, w.one)}</span>}
              {leads(a) && <span className="hint"> · moves here from {colonyName(a, w.one)}, its {w.one} of one</span>}
            </label>)}
          </div>}
        </>}
      <div className="row">
        <button onClick={onDone}>Cancel</button>
        <button className="primary" disabled={busy || !name.trim() || dup || (empty && !!initial)}
          onClick={() => act(async () => { await (empty ? onEmpty({ name: name.trim(), about: about.trim() }) : create()); onDone() })}>
          {initial ? `Add to ${w.one}` : empty ? `Create empty ${w.one}` : `Create ${w.one}`}</button>
      </div>
    </div>
  )
}

/** A colony's name and what it's for, edited in place. */
function ColonyFields({ name: name0, about: about0, busy, onSave, onCancel }: {
  name: string; about: string; busy: boolean
  onSave: (name: string, about: string) => void; onCancel: () => void
}) {
  const [name, setName] = useState(name0)
  const [about, setAbout] = useState(about0)
  const w = useTeamWord()
  return (
    <form className="colony-edit" onSubmit={e => { e.preventDefault(); if (name.trim()) onSave(name.trim(), about.trim()) }}>
      <input autoFocus value={name} maxLength={60} onChange={e => setName(e.target.value)} aria-label={`${w.One} name`} />
      <input value={about} maxLength={300} onChange={e => setAbout(e.target.value)} placeholder="What it's for" aria-label="What it's for" />
      <div className="row tight">
        <button className="primary" disabled={busy || !name.trim()}>Save</button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
