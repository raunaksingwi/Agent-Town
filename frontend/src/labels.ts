// What a run's state is called, in the town's words and in the workspace's plain ones.

import type { ChatMessage, MailSaid, RunStatus } from './api'

/** The town: an agent is a character, so it wakes, works and sleeps */
export const RUN_STATUS_TOWN: Record<RunStatus, string> = {
  starting: 'waking up…', ready: 'awake', busy: 'working…', stopped: 'asleep', error: 'something went wrong',
}
/** The workspace and the chat app: plain words */
export const RUN_STATUS_PLAIN: Record<RunStatus, string> = {
  starting: 'Starting', ready: 'Active', busy: 'Working', stopped: 'Idle', error: 'Error',
}

/** The last thing said, as one line; nothing yet: what the agent is for */
export function preview(m: ChatMessage | null, description: string, team = 'colony'): string {   // team: 'cabin' in the Office
  if (!m) return description || 'Say hello'
  if (m.kind === 'approval' && (m.data.type === 'agent' || m.data.type === 'colony'))
    return `🏠 ${m.data.state === 'sent' ? 'Added' : 'Add'} ${m.data.type === 'agent' ? 'agent' : team} ${String(m.data.name)}`
  if (m.kind === 'approval' && m.data.type === 'post') return `💼 ${m.data.state === 'sent' ? 'Posted' : 'Post'} on LinkedIn`
  if (m.kind === 'approval') return `✉️ ${m.data.state === 'sent' ? 'Sent' : 'Email'} to ${String(m.data.to)}`
  if (m.kind === 'mail') return `✉ Mail from ${((m.data.said ?? []) as MailSaid[]).map(x => x.from).join(', ')}`
  const text = String(m.data.text ?? '').replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim()
  return (m.kind === 'user' ? 'You: ' : m.routine ? `${m.routine}: ` : '') + text
}
