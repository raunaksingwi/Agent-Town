// Settings (the menu under your name): everything you set up now and then, in one place. Your look, which
// styles the whole app (look.tsx): the town or the office, the panels, the chat, the chat app on your phone,
// the title and the fonts. Then your account and AI, what your agents know about you, your colonies and
// your apps: each opens its own screen, and closing that screen comes back here (App.tsx).

import { TEAM_WORDS, type Look } from './look'
import { Modal } from './ui'

const LOOKS: { key: Look; name: string; says: string }[] = [
  { key: 'retro', name: 'Retro', says: 'A 16-bit game town. Pixel title, parchment panels, characters walking about.' },
  { key: 'fantasy', name: 'Fantasy', says: 'The same town as a painted map.' },
  { key: 'office', name: 'Office', says: 'A work tool. A cabin per team, clean panels, a notes-style chat, plain words.' },
]

export type SettingsScreen = 'account' | 'profile' | 'colonies' | 'apps'
const screens = (look: Look): { group: string; rows: { key: SettingsScreen; name: string; says: string }[] }[] => [
  { group: 'You', rows: [
    { key: 'account', name: 'Account and AI models', says: 'Your sign-in, and the Claude or ChatGPT account your agents think with' },
    { key: 'profile', name: 'About you and your company', says: 'What every one of your agents knows about you' },
  ] },
  { group: look === 'office' ? 'Your office' : 'Your town', rows: [
    { key: 'colonies', name: TEAM_WORDS[look === 'office' ? 'office' : 'town'].Many, says: 'Your teams: a lead and the agents it hands work to' },
    { key: 'apps', name: 'Connect apps', says: 'Gmail, Notion, GitHub and more: connect once, then choose per agent' },
  ] },
]

export function SettingsModal({ look, onPick, onOpen, onClose }: {
  look: Look; onPick: (look: Look) => void; onOpen?: (screen: SettingsScreen) => void; onClose: () => void
}) {
  return (
    <Modal title="Settings" onClose={onClose}>
      <h3 className="settings-h">Look</h3>
      <p className="hint">Changes the whole app: the town, its panels and chat, and the chat app on your phone. Saved with your account.</p>
      <div className="looks" role="radiogroup" aria-label="Look">
        {LOOKS.map(l => (
          <button key={l.key} role="radio" aria-checked={look === l.key} className={`look-card${look === l.key ? ' on' : ''}`} onClick={() => onPick(l.key)}>
            <span className={`look-sample ${l.key}`} aria-hidden="true"><b>Agent Town</b><i /><i /><i /></span>
            <span className="look-name">{l.name}{look === l.key && <span className="look-on"> · in use</span>}</span>
            <span className="look-says">{l.says}</span>
          </button>
        ))}
      </div>
      {onOpen && screens(look).map(g => <section key={g.group} className="settings-group">
        <h3 className="settings-h">{g.group}</h3>
        <div className="settings-rows">{g.rows.map(r =>
          <button key={r.key} className="settings-row" onClick={() => onOpen(r.key)}>
            <span className="settings-row-text"><b>{r.name}</b><span>{r.says}</span></span><span className="settings-go" aria-hidden>›</span>
          </button>)}</div>
      </section>)}
    </Modal>
  )
}
