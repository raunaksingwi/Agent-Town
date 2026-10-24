// The front door for an empty town (an account made before the mayor, or one that deleted everything):
// meet the mayor, who builds the town with you, or pick your own agents. New accounts get the mayor at
// sign-up and land in its chat. Telling agents about yourself comes after (profile.tsx).

import { useState } from 'react'
import { api, type City } from './api'
import { usePlain } from './look'
import { AssistantName } from './modals'
import { Err, LinkButton, Modal, msg } from './ui'

export function WelcomeModal({ city, reload, onClose, onAdd, onStart }: {
  city: City; reload: () => Promise<void>; onClose: () => void
  onAdd: () => void; onStart: (mayorId: number) => void
}) {
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const office = usePlain()           // the Office look: seats and rooms, not houses and walking about

  async function start() {
    setBusy(true); setError(null)
    try {
      const r = await api.installStarter(name)
      await reload()
      onStart(r.agent.id)
    } catch (e) { setError(msg(e)); setBusy(false) }
  }

  return (
    <Modal title={`Welcome, @${city.me?.username}`} onClose={onClose} wide>
      <p className="hint">{office
        ? 'Your AI helpers work here. Each has a name, a seat at its team\'s table and one job, and you chat with them like teammates.'
        : 'Your AI helpers live here. Each has a name, a house and a job, and you chat with them like teammates.'}</p>
      <div className="form"><AssistantName value={name} onChange={setName} /></div>
      <div className="welcome-choices">
        <button className="welcome-choice primary-choice" disabled={busy} onClick={start}>
          <b>{busy ? 'On the way…' : `Meet ${name.trim() || 'your mayor'}`}</b>
          <span>Tell {name.trim() || 'the mayor'} what you need done. It works out which agents and teams would do it best, asks
            what they should know, and sets them up with you. {office
              ? 'It works at reception, the first cabin in your office: click its card to talk.'
              : 'It walks with you around town: press M to talk.'}</span>
        </button>
        <button className="welcome-choice" disabled={busy} onClick={onAdd}>
          <b>I'll pick my own agents</b>
          <span>From the agent market, or bring your own <code>.md</code> file or <code>.claude</code> folder.</span>
        </button>
      </div>
      <Err error={error} />
      <p className="switch"><LinkButton onClick={onClose}>Just look around first</LinkButton></p>
    </Modal>
  )
}
