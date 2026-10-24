// Times as people say them. One place, so "yesterday" means the same everywhere.

const DAY = 86_400_000
const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
/** Whole days from today to `d`: 0 today, -1 yesterday, 1 tomorrow */
const dayDiff = (d: Date) => Math.round((midnight(d) - midnight(new Date())) / DAY)
const clock = (d: Date) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

/** "just now", "5m ago", "3h ago", "2d ago"; "never" for nothing */
export function ago(iso: string | null): string {
  if (!iso) return 'never'
  const s = (Date.now() - Date.parse(iso)) / 1000
  return s < 60 ? 'just now' : s < 3600 ? `${(s / 60) | 0}m ago` : s < 86400 ? `${(s / 3600) | 0}h ago` : `${(s / 86400) | 0}d ago`
}

/** "14:05", "Yesterday", "Mon", "3 Oct": a message list's timestamp */
export function short(iso: string): string {
  const d = new Date(iso), days = -dayDiff(d)
  if (days === 0) return clock(d)
  if (days === 1) return 'Yesterday'
  if (days < 7) return d.toLocaleDateString([], { weekday: 'short' })
  return d.toLocaleDateString([], { day: 'numeric', month: 'short' })
}

/** "Today 08:02", "Yesterday 16:00", "Tomorrow 09:00", "Mon 13 Oct 09:00" */
export function when(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso), diff = dayDiff(d), time = clock(d)
  if (diff === 0) return `Today ${time}`
  if (diff === -1) return `Yesterday ${time}`
  if (diff === 1) return `Tomorrow ${time}`
  return `${d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} ${time}`
}

/** Just the date, or "never" */
export const onDay = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : 'never')

/** "today", "yesterday", "3 days ago" from a count of days */
export const daysAgo = (days: number) => days === 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`
