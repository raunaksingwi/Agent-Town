// The tour: what's on the map and how to get around, a few cards at a time. It opens once after
// sign-up and again from the menu ("How Agent Town works"), instead of a key that sits on the map for good.
// In the Office look (look.tsx) it tours the office's cabins instead: no houses, nobody walking about.

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { usePlain } from './look'
import { Modal } from './ui'

type Step = { icon: string; title: string; body: ReactNode }

/** The Office's tour: its cabins, their cards, and how to move between them. */
function officeSteps(mayor: string | undefined, phone: boolean): Step[] {
  return [
    { icon: '🏢', title: 'Welcome to your office', body: <>
      Your AI agents work here. Each one has a name, a seat at its team's table and one job, and you chat with them like
      teammates. <b>Today</b> shows what they did and what's waiting on you; <b>Office</b> is where you go to talk to them.</> },
    ...(mayor ? [{ icon: '🛎️', title: `${mayor} is at reception`, body: <>
      {mayor.toLowerCase() !== 'mayor' && <>{mayor} is your mayor. </>}It works at the reception desk, the first cabin. Tell it what you want done: it works out which agents you need, sets them up with you and keeps the office
      running. {phone ? 'Tap' : 'Click'} its card to talk.</> }] : []),
    { icon: '🗂️', title: 'Reading a cabin', body: <dl className="tour-key">
      <dt>🚪 Cabin</dt><dd>a team: its lead at the head of the table, the others along the sides.</dd>
      <dt>🪪 Card</dt><dd>an agent: what it's on now. Green is working, amber wants you, grey is asleep.</dd>
      <dt>🧩 Apps</dt><dd>along the room's wall, like Gmail. The dots show which agents use each one.</dd>
      <dt>📮 Mail</dt><dd>the team's mail, in the room's top bar. <b>N want you</b> at the top finds who's waiting.</dd>
    </dl> },
    { icon: phone ? '👆' : '🖱️', title: 'Working here', body: phone
      ? <ul className="tour-list"><li>Tap a card to chat with that agent.</li><li><b>Details</b> in the chat has its instructions,
        files, memory and apps.</li><li>Swipe the tabs to go to another cabin, or open <b>All cabins</b>.</li></ul>
      : <ul className="tour-list"><li>Click a card to chat with that agent. <b>Details</b> in the chat has its instructions,
        files, memory and apps.</li><li>The tabs, the arrows or <kbd>←</kbd> <kbd>→</kbd> take you from cabin to cabin.</li>
        <li><b>All cabins</b> zooms out to every cabin at once, with who wants you.</li></ul> },
    { icon: '❓', title: 'Stuck? Ask', body: <>
      The <b>?</b> button in the corner is the caretaker: ask it how anything works, or to find something for you.
      You can see this tour again from your menu, under <b>How Agent Town works</b>.</> },
  ]
}

export function TourModal({ mayor, phone, onClose }: { mayor?: string; phone: boolean; onClose: () => void }) {
  const office = usePlain()
  const steps: Step[] = office ? officeSteps(mayor, phone) : [
    { icon: '🏘️', title: 'Welcome to your town', body: <>
      Your AI agents live here. Each one has a name, a house and one job, and you chat with them like teammates.
      <b> Today</b> shows what they did and what's waiting on you; <b>Town</b> is where you go to talk to them.</> },
    ...(mayor ? [{ icon: '🎩', title: `${mayor} walks with you`, body: <>
      {mayor.toLowerCase() !== 'mayor' && <>{mayor} is your mayor. </>}Tell it what you want done: it works out which
      agents you need, sets them up with you and keeps the town running.{' '}
      {phone ? <>Tap {mayor} to talk.</> : <>Press <kbd>M</kbd> anywhere on the map to talk.</>}</> }] : []),
    { icon: '🏠', title: 'Reading the map', body: <dl className="tour-key">
      <dt>🏠 House</dt><dd>an agent. Walk up and go inside to chat, or see its notes and files.</dd>
      <dt>🛒 Stall</dt><dd>an app its team can use, like Gmail. The same icon shows on the house.</dd>
      <dt>▢ Colony</dt><dd>a team: the lead stands in front and hands work to the others.</dd>
      <dt>📮 Post office</dt><dd>the colony's mail. A lead waiting in the square has news for you.</dd>
    </dl> },
    { icon: phone ? '👆' : '⌨️', title: 'Getting around', body: phone
      ? <ul className="tour-list"><li>Drag to look around, pinch to zoom.</li><li>Tap a house to talk to its agent.</li>
        <li>Tap the ground to walk there.</li></ul>
      : <ul className="tour-list"><li><kbd>W</kbd> <kbd>A</kbd> <kbd>S</kbd> <kbd>D</kbd> or the arrows to walk, <kbd>Shift</kbd> to run.</li>
        <li><kbd>E</kbd> to talk to the agent you're next to.</li><li>Click the ground to walk there, or a building to open it.</li></ul> },
    { icon: '❓', title: 'Stuck? Ask', body: <>
      The <b>?</b> button in the corner is the caretaker: ask it how anything works, or to find something for you.
      You can see this tour again from your menu, under <b>How Agent Town works</b>.</> },
  ]
  const [i, setI] = useState(0)
  const last = i === steps.length - 1
  // ← and → page through (the Modal already owns Escape and Tab)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest?.('input, textarea')) return
      if (e.key === 'ArrowRight') setI(n => Math.min(n + 1, steps.length - 1))
      else if (e.key === 'ArrowLeft') setI(n => Math.max(n - 1, 0))
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [steps.length])
  const s = steps[i]
  // Enter goes forward: start on Next, not on the first dot (the Modal focuses the first button it finds)
  const next = useRef<HTMLButtonElement>(null)
  useEffect(() => { next.current?.focus() }, [])

  return (
    <Modal title="How Agent Town works" onClose={onClose}>
      <div className="tour" aria-live="polite">
        <div className="tour-icon" aria-hidden>{s.icon}</div>
        <h3>{s.title}</h3>
        <div className="tour-body">{s.body}</div>
      </div>
      <div className="tour-foot">
        <div className="tour-dots" role="tablist" aria-label="Steps">{steps.map((x, n) =>
          <button key={n} role="tab" aria-selected={n === i} aria-label={x.title} tabIndex={-1} className={n === i ? 'on' : ''} onClick={() => setI(n)} />)}</div>
        <span className="grow" />
        {i > 0 ? <button onClick={() => setI(i - 1)}>Back</button> : <button onClick={onClose}>Skip</button>}
        <button ref={next} className="primary" onClick={last ? onClose : () => setI(i + 1)}>{last ? 'Got it' : 'Next'}</button>
      </div>
    </Modal>
  )
}
