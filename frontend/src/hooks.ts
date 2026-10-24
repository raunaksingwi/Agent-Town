// Hooks the three surfaces (the town, the workspace, the chat app) share.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, UNAUTHENTICATED, type Credential } from './api'
import { NOTICE_MS } from './ui-constants'

export type Notice = { ok: boolean; text: string } | null

/** Back from a sign-in (Google's, LinkedIn's or an app's): say how it went, and pick up "Make it your own"
 *  where it was. The query string is cleaned up so a reload doesn't say it twice. */
export function useSignInReturn(setNotice: (n: Notice) => void, resume: (agentId: number) => void) {
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    const connected = q.get('connected'), failed = q.get('connect_error')
    if (!connected && !failed) return
    // Google says which of its apps (or "none"); LinkedIn says "linkedin"; any other app's sign-in, its name
    const names = (connected ?? '').split(',').map(a => a === 'gmail' ? 'Gmail' : a === 'calendar' ? 'Google Calendar' : a === 'linkedin' ? 'LinkedIn' : a === 'none' ? '' : a).filter(Boolean)
    setNotice(failed ? { ok: false, text: failed } : { ok: true, text: names.length ? `Connected ${names.join(' and ')}.` : 'Google didn\'t grant any access.' })
    window.history.replaceState(null, '', window.location.pathname)
    try {
      const r = sessionStorage.getItem('agenttown.resumeSetup')
      sessionStorage.removeItem('agenttown.resumeSetup')
      if (r) resume(Number(r))
    } catch { /* private mode */ }
    const t = window.setTimeout(() => setNotice(null), NOTICE_MS)
    return () => clearTimeout(t)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
}

/** Back from "Continue with Google" (backend/app/routers/auth.py): a new account, which starts on its
 *  assistant, or why it didn't work. Read once; the address is cleaned so a reload doesn't repeat it. */
export function useGoogleReturn(): { error: string | null; isNew: boolean } {
  const [r] = useState(() => {
    const q = new URLSearchParams(window.location.search)
    return { error: q.get('signin_error'), isNew: q.get('signed_up') === '1' }
  })
  useEffect(() => {
    const q = new URLSearchParams(window.location.search)
    if (!q.has('signin_error') && !q.has('signed_up')) return
    q.delete('signin_error'); q.delete('signed_up')
    window.history.replaceState(null, '', window.location.pathname + (q.size ? `?${q}` : ''))
  }, [])
  return r
}

/** The session cookie expired (any call answered 401): do this once, e.g. reload and offer Sign in. */
export function useUnauthenticated(handler: () => void) {
  const h = useRef(handler)
  useLayoutEffect(() => { h.current = handler })
  useEffect(() => {
    const on = () => h.current()
    window.addEventListener(UNAUTHENTICATED, on)
    return () => window.removeEventListener(UNAUTHENTICATED, on)
  }, [])
}

/** Call `tick` now and every `every()` ms (re-read after each tick), but not while the tab is hidden:
 *  it resumes, with an immediate tick, when the tab shows again. `deps` restart it. */
export function usePoll(tick: () => Promise<unknown> | void, every: () => number, deps: unknown[], on = true) {
  const fn = useRef(tick), gap = useRef(every)
  useLayoutEffect(() => { fn.current = tick; gap.current = every })
  useEffect(() => {
    if (!on) return
    let stop = false, timer = 0, running = false
    const run = async () => {
      if (stop || running || document.visibilityState === 'hidden') return
      running = true
      try { await fn.current() } catch { /* the tick reports its own errors */ } finally { running = false }
      if (!stop) timer = window.setTimeout(run, gap.current())
    }
    const visible = () => { if (document.visibilityState === 'visible') { clearTimeout(timer); run() } }
    document.addEventListener('visibilitychange', visible)
    run()
    return () => { stop = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [on, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
}

// ---- the AI accounts, fetched once and shared ------------------------------------------------------

type Creds = { allow_subscription_tokens: boolean; credentials: Credential[] }
let cache: Creds | null = null
let inflight: Promise<Creds> | null = null
const listeners = new Set<(c: Creds | null) => void>()

function fetchCreds(): Promise<Creds> {
  if (!inflight) inflight = api.credentials().then(c => { cache = c; listeners.forEach(l => l(c)); return c }).finally(() => { inflight = null })
  return inflight
}
/** Something changed the AI accounts (added, removed, checked, signed out): every screen looks again. */
export function invalidateCredentials() {
  cache = null
  listeners.forEach(l => l(null))
  if (listeners.size) fetchCreds().catch(() => {})
}

/** Your AI accounts: `null` while unknown. Every caller shares one request and one cache. */
export function useCredentials(): { creds: Credential[] | null; subs: boolean; refresh: () => void } {
  const [data, setData] = useState<Creds | null>(cache)
  useEffect(() => {
    listeners.add(setData)
    if (!cache) fetchCreds().catch(() => setData({ allow_subscription_tokens: true, credentials: [] }))
    return () => { listeners.delete(setData) }
  }, [])
  const refresh = useCallback(() => invalidateCredentials(), [])
  return { creds: data?.credentials ?? null, subs: data?.allow_subscription_tokens ?? true, refresh }
}

/** The signed-in person changed (sign in, sign out): forget what the last one had. */
export function forgetCredentials() { cache = null; listeners.forEach(l => l(null)) }

/** Whether the screen is phone-sized (at or under `bp` px), live */
export function useNarrow(bp: number): boolean {
  const [narrow, setNarrow] = useState(() => typeof matchMedia === 'function' && matchMedia(`(max-width: ${bp}px)`).matches)
  useEffect(() => {
    const m = matchMedia(`(max-width: ${bp}px)`)
    const on = () => setNarrow(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [bp])
  return narrow
}
