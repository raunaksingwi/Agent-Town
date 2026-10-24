// Small shared pieces: modal, markdown, error line.

import { Suspense, lazy, useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const Markdown = lazy(() => import('react-markdown'))     // the biggest dependency, only needed once something is read

// ---- modals: one keyboard owner at a time ----------------------------------------------------------
// Every open modal is on this stack. Only the top one answers Escape, and it stops the key there, so a
// file editor inside a house closes alone (not the house, not the dialogue behind it). While any modal
// is open the page behind (#root) is inert: no clicks, no focus, no keys reach it.
const stack: symbol[] = []
export const modalsOpen = () => stack.length

const FOCUSABLE = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  const me = useRef(Symbol('modal'))
  const close = useRef(onClose)
  useLayoutEffect(() => { close.current = onClose })

  useLayoutEffect(() => {
    const id = me.current, before = document.activeElement as HTMLElement | null
    stack.push(id)
    const root = document.getElementById('root')
    root?.setAttribute('inert', '')
    // focus goes in: the first thing you can use (not the × in the corner: Enter mustn't close what just
    // opened), else the title, so the keyboard is in the dialog
    const first = [...box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []].find(el => !el.closest('.modal-head'))
    if (!box.current?.querySelector('[autofocus]')) (first ?? box.current?.querySelector<HTMLElement>('h2'))?.focus()
    return () => {
      stack.splice(stack.indexOf(id), 1)
      if (!stack.length) root?.removeAttribute('inert')
      before?.focus?.()
    }
  }, [])

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== me.current) return     // another modal is on top
      if (e.key === 'Escape') { e.stopImmediatePropagation(); e.preventDefault(); close.current() }
      else if (e.key === 'Tab' && box.current) {               // Tab stays inside the dialog
        const all = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(el => el.offsetParent !== null)
        if (!all.length) return
        const i = all.indexOf(document.activeElement as HTMLElement)
        if (e.shiftKey && i <= 0) { e.preventDefault(); all[all.length - 1].focus() }
        else if (!e.shiftKey && (i === -1 || i === all.length - 1)) { e.preventDefault(); all[0].focus() }
      }
    }
    window.addEventListener('keydown', k, true)
    return () => window.removeEventListener('keydown', k, true)
  }, [])

  return createPortal(
    <div className="backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div ref={box} className={`modal${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h2 tabIndex={-1}>{title}</h2><button className="x" onClick={onClose} aria-label="Close">×</button></div>
        {children}
      </div>
    </div>, document.body)
}

// ---- markdown ---------------------------------------------------------------------------------------
const host = (href: string) => { try { return new URL(href, location.href).host } catch { return '' } }
/** A link in something an agent wrote: opens in a new tab (never in place of the app), and says where it
 *  goes, since what an agent writes can be steered by an email it read. */
function Link({ href, children, ...rest }: React.ComponentProps<'a'>) {
  const h = href ? host(href) : ''
  const external = !!h && h !== location.host
  return <a {...rest} href={href} target="_blank" rel="noopener noreferrer">{children}{external && <span className="md-host"> ({h})</span>}</a>
}

export function Md({ text }: { text: string }) {
  const body = text.replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, '')
  return <div className="md"><Suspense fallback={<p style={{ whiteSpace: 'pre-wrap' }}>{body}</p>}><Markdown components={{ a: Link }}>{body}</Markdown></Suspense></div>
}

export function Err({ error }: { error: string | null }) {
  return error ? <p className="err">{error}</p> : null
}

export const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Only a web address may be followed from data an agent produced; anything else is shown but not linked. */
export const safeHref = (url: unknown): string | undefined => (typeof url === 'string' && /^https?:\/\//i.test(url) ? url : undefined)

export function readFiles(list: FileList | null): Promise<{ path: string; content: string }[]> {
  return Promise.all([...(list ?? [])].map(f => f.text().then(content => ({ path: f.name, content }))))
}

/** Something that reads like a link in a sentence, but is a button (it goes nowhere, so it isn't a link) */
export function LinkButton({ onClick, children, className }: { onClick: () => void; children: ReactNode; className?: string }) {
  return <button type="button" className={`linklike${className ? ` ${className}` : ''}`} onClick={onClick}>{children}</button>
}
