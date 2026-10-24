// About you and your company, told once: a shared file (about-us.md) every one of your agents reads,
// so no agent has to ask who you are. It's optional and never asked up front: you hand over what you
// already have (your website, an About page, a resume or bio), and a few questions if you like.

import { useEffect, useState } from 'react'
import { api, type City } from './api'
import { Err, LinkButton, Modal, msg, readFiles } from './ui'

export const PROFILE_FILE = 'about-us.md'
export const PROFILE_QUESTIONS = [
  'What should your agents call you, and what do you do?',
  'What does your company do, and for whom?',
  'What are your top goals for the next 90 days?',
  'Who else is on the team, and who does what?',
  'How do you write? Paste an email or post that sounds like you.',
  'What should your agents never do without asking you first?',
]
const OWN = 'In their own words'          // what they pasted: a bio, a resume, a LinkedIn About
const FROM = 'From '                      // "From https://…": a page we read for them

export type Answers = Record<string, string>

/** These notes are "## heading" then the text, so they read well to an agent and to you. */
export function parseAnswers(text: string): Answers {
  const out: Answers = {}
  for (const block of text.split(/^## /m).slice(1)) {
    const [q, ...rest] = block.split('\n')
    out[q.trim()] = rest.join('\n').trim()
  }
  return out
}

/** Writes the answers to `questions`, keeping answers to questions that aren't asked any more. */
export function writeAnswers(title: string, questions: string[], answers: Answers, previous = ''): string {
  const kept = Object.entries(parseAnswers(previous)).filter(([q, a]) => !questions.includes(q) && a)
  const blocks = [...questions.filter(q => answers[q]?.trim()).map(q => [q, demote(answers[q].trim())]), ...kept]
  return `# ${title}\n\n` + blocks.map(([q, a]) => `## ${q}\n\n${a}\n`).join('\n')
}

// pasted markdown can carry its own "## " headings, which would split one answer into two
const demote = (text: string) => text.replace(/^#{1,2} /gm, '### ')
const words = (text: string) => text.split(/\s+/).filter(Boolean).length
export const hasAnswers = (questions: string[], a: Answers) => questions.some(q => a[q]?.trim())

/** The profile as saved in your shared files. `custom` means you wrote about-us.md yourself, in your
 *  own words with no sections: agents read it as it is, and we don't offer to rewrite it. */
export function useProfile(city: City) {
  const file = city.shared_files.find(f => f.path === PROFILE_FILE)
  const [text, setText] = useState<string | null>(file ? null : '')
  useEffect(() => {
    if (!file) { setText(''); return }
    api.sharedFile(file.id).then(f => setText(f.content), () => setText(''))
  }, [file?.id, file?.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps
  const saved = parseAnswers(text ?? '')
  return { loaded: text !== null, text: text ?? '', saved, filled: !!text?.trim(), custom: !!text?.trim() && !Object.keys(saved).length }
}

type Page = { url: string; text: string }

export function ProfileModal({ city, reload, onClose }: { city: City; reload: () => Promise<void>; onClose: () => void }) {
  const profile = useProfile(city)
  const [own, setOwn] = useState('')
  const [pages, setPages] = useState<Page[]>([])
  const [answers, setAnswers] = useState<Answers>({})
  const [moreOpen, setMoreOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [reading, setReading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [started, setStarted] = useState(false)

  // start from what's saved, once it has loaded
  useEffect(() => {
    if (!profile.loaded || started) return
    const s = profile.saved
    setOwn(s[OWN] ?? '')
    setPages(Object.entries(s).filter(([k]) => k.startsWith(FROM)).map(([k, text]) => ({ url: k.slice(FROM.length), text })))
    setAnswers(s); setMoreOpen(hasAnswers(PROFILE_QUESTIONS, s)); setStarted(true)
  }, [profile.loaded]) // eslint-disable-line react-hooks/exhaustive-deps

  async function readPage() {
    if (!url.trim()) return
    setReading(true); setError(null)
    try {
      const p = await api.readPage(url.trim())
      setPages([...pages.filter(x => x.url !== p.url), { url: p.url, text: p.text }]); setUrl('')
    } catch (e) { setError(msg(e)) } finally { setReading(false) }
  }

  async function save() {
    setBusy(true); setError(null)
    try {
      const all: Answers = { ...answers, [OWN]: own }
      for (const p of pages) all[FROM + p.url] = p.text
      const ours = [OWN, ...pages.map(p => FROM + p.url), ...PROFILE_QUESTIONS]
      // a page they removed shouldn't come back from the old file
      const previous = writeAnswers('About us', [], Object.fromEntries(Object.entries(profile.saved)
        .filter(([k]) => !k.startsWith(FROM) && k !== OWN && !PROFILE_QUESTIONS.includes(k))))
      if (hasAnswers(ours, all)) await api.putSharedFile(PROFILE_FILE, writeAnswers('About us', ours, all, previous))
      else if (profile.filled) await api.putSharedFile(PROFILE_FILE, previous)
      await reload(); onClose()
    } catch (e) { setError(msg(e)) } finally { setBusy(false) }
  }

  if (profile.custom) return (
    <Modal title="Tell your team about you" onClose={onClose}>
      <p className="hint">Your agents already read the <code>{PROFILE_FILE}</code> you wrote. Edit it any time in <b>Shared files</b>.</p>
      <div className="row"><span className="grow" /><button className="primary" onClick={onClose}>OK</button></div>
    </Modal>
  )

  return (
    <Modal title="Tell your team about you" onClose={onClose} wide>
      <p className="hint">Hand over what you already have, and every one of your agents will know who you are and what your company
        does. All of it is optional. It's saved as <code>{PROFILE_FILE}</code> in your shared files.</p>
      {!profile.loaded ? <p className="hint">Loading…</p> : <div className="form">
        <label>Your website, or any public page about you
          <span className="url-row">
            <input type="url" placeholder="yourcompany.com/about" value={url} onChange={e => setUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); readPage() } }} />
            <button disabled={reading || !url.trim()} onClick={readPage}>{reading ? 'Reading…' : 'Read it'}</button>
          </span>
        </label>
        {pages.length > 0 && <ul className="list pages">{pages.map(p => (
          <li key={p.url}><span className="grow">✓ {p.url}</span><span className="meta">{words(p.text).toLocaleString()} words</span>
            <button className="tiny" title="Remove" onClick={() => setPages(pages.filter(x => x.url !== p.url))}>✕</button></li>))}</ul>}

        <label>Paste anything about you
          <span className="hint">Your LinkedIn About, a resume, a bio, your pitch. Have a PDF? Open it and copy the text.</span>
          <textarea rows={6} value={own} onChange={e => setOwn(e.target.value)} />
        </label>
        <label className="linklike">or add a text file (.md, .txt)
          <input type="file" multiple accept=".md,.txt" hidden onChange={async e => {
            const picked = await readFiles(e.target.files)
            setOwn([own, ...picked.map(f => f.content)].filter(t => t.trim()).join('\n\n'))
          }} /></label>

        {moreOpen ? <>
          <h3>A few questions, if you like</h3>
          {PROFILE_QUESTIONS.map((q, i) => (
            <label key={q}>{q}
              <textarea id={`profile-${i}`} rows={q.includes('Paste') ? 4 : 2} value={answers[q] ?? ''}
                onChange={e => setAnswers({ ...answers, [q]: e.target.value })} /></label>))}
        </> : <LinkButton className="more-qs" onClick={() => setMoreOpen(true)}>
          + Answer a few questions too (goals, team, what needs your yes)</LinkButton>}
      </div>}
      <Err error={error} />
      <div className="row">
        <button onClick={onClose}>Later</button>
        <span className="grow" />
        <button className="primary" disabled={busy || !profile.loaded} onClick={save}>{busy ? 'Saving…' : 'Save for all my agents'}</button>
      </div>
    </Modal>
  )
}
