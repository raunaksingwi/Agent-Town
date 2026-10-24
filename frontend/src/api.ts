// Typed calls to the backend. Every request sends the session cookie (same origin).

export type User = { id: number; username: string; email: string; has_password: boolean; google: boolean }

export type FileStat = { id: number; path: string; lines: number; bytes: number; updated_at: string }
export type FileFull = FileStat & { content: string; share_id?: number | null; agent?: string }

export type AgentSummary = {
  id: number; slug: string; name: string; description: string; color: string; owner: string
  building: string; files: FileStat[]; lines: number
}
export type Grant = { connection_id: number; tool_name: string | null }
export type MyAgent = Omit<AgentSummary, 'files'> & {
  files: FileFull[]; grants: Grant[]; share_id: number | null; can_use_public: boolean
  model_credential_id: number | null; model: string; thinking: Thinking; brain: Brain | null; run_status?: RunStatus | null; team: number[]
  memory: string; email_policy: EmailPolicy; post_policy: PostPolicy
  colony_name: string; colony_about: string   // when it leads a team: the colony's name and what it's for
  role?: '' | 'mayor'                          // the mayor walks with you: no house, no colony (backend/app/mail.py)
}
/** When an email it sends may go out without your Send (backend/app/outbox.py) */
export type EmailPolicy = { mode: 'ask' | 'auto'; to: 'known' | 'anyone'; allow: string[]; replies_only: boolean }
/** Whether a LinkedIn post it writes goes out at once or waits for your Post (backend/app/outbox.py) */
export type PostPolicy = { mode: 'ask' | 'auto' }

export type Brain = { provider: Provider; model: string; thinking: Thinking }
export type Thinking = '' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
export type RunStatus = 'starting' | 'ready' | 'busy' | 'stopped' | 'error'

export type ApiToken = { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null; expires_at: string | null }
export type Provider = 'anthropic' | 'openai'
export type CredKind = 'api_key' | 'subscription'
export type Credential = {
  id: number; provider: Provider; kind: CredKind; label: string; hint: string; is_default: boolean
  status: 'unverified' | 'valid' | 'invalid' | 'error'; status_detail: string; last_checked_at: string | null
}

export type Status = 'unknown' | 'connected' | 'auth_required' | 'error' | 'needs_sandbox'
export type Connection = {
  id: number; name: string; transport: 'http' | 'stdio' | 'hosted' | 'web'; url: string | null; command: string | null
  app: string; oauth_account_id: number | null
  has_auth: boolean; header_names: string[]; env_names: string[]
  sign_in: 'none' | 'available' | 'signed_in'; own_client: boolean   // the app's own sign-in (MCP OAuth)
  status: Status; status_detail: string; server_name: string; server_version: string
  last_checked_at: string | null; tools: { name: string; description: string }[]
  granted_to: { agent_id: number; agent: string; tool_name: string | null }[]
}

export type NewConnection = {
  name: string; transport: 'http' | 'stdio' | 'web'; url?: string; command?: string; auth_header?: string
  headers?: Record<string, string>; env?: Record<string, string>; oauth_client_id?: string; oauth_client_secret?: string
}

export type Share = {
  id: number; kind: 'agent' | 'file'; title: string; note: string; owner: string
  allow_agent_use: boolean; created_at: string
  agent?: Omit<AgentSummary, 'files'> & { files: (FileStat | FileFull)[] }
  file?: FileFull | (FileStat & { agent: string })
}

export type Run = {
  id: number; agent_id: number; routine_id: number | null; status: RunStatus; detail: string; provider: string
  created_at: string; last_active_at: string; ended_at: string | null
}
export type RunEvent = {
  id: number; created_at: string
  kind: 'user' | 'text' | 'tool' | 'tool_result' | 'done' | 'status' | 'error' | 'approval' | 'notice' | 'mail'
  data: Record<string, unknown>
}

export type Routine = {
  id: number; agent_id: number; agent: string; name: string; prompt: string
  days: string; at: string; timezone: string; enabled: boolean   // days: digits, Monday=0 ("01234" = weekdays)
  trigger: 'schedule' | 'email'                                  // email: when mail arrives from someone you've written to
  when: string; next_run_at: string | null; last_run: Run | null
}
export type RoutineIn = Partial<Pick<Routine, 'agent_id' | 'name' | 'prompt' | 'days' | 'at' | 'timezone' | 'enabled' | 'trigger'>>
export type AgentRef = { id: number; name: string; color: string }
export type RoutineResult = {
  run: Run; routine: string; agent: AgentRef; report: string
  steps: { tool: string; count: number }[]; done: { ok?: boolean; cost_usd?: number; duration_ms?: number }; errors: string[]
}
/** An email thread waiting on someone (backend/app/mailindex.py) */
export type Loop = { thread_id: string; email_id: string; subject: string; with: string; email: string; at: string; days: number }
export type Mail = { run_id: number; event: RunEvent; agent: AgentRef; routine: string | null }
export type Today = {
  waiting: Mail[]       // waiting for your Send
  outgoing: Mail[]      // going out by its rules, still in the undo wait
  sent: Mail[]          // the last week, newest first
  loops: { waiting_on_me: Loop[]; gone_quiet: Loop[]; indexing: boolean }   // from the email index
  results: RoutineResult[]
  routines: Routine[]
  suggested: { slug: string; name: string; days: string; at: string; prompt: string; trigger?: 'schedule' | 'email'; agent_id: number; agent: string }[]
}

/** Mail between colonies, and to you (backend/app/mail.py). from/to null: you */
export type MailWho = { id: number; name: string; color: string; colony: string }
export type Letter = {
  id: number; thread_id: number; subject: string; body: string; options: string[]; answer: string
  kind: 'message' | 'question' | 'fyi' | 'guard'      // guard: a thread paused at its limit, asking you whether it goes on
  state: 'waiting' | 'queued' | 'delivered' | 'held' | 'dropped' | 'new' | 'answered' | 'read'
  from: MailWho | null; to: MailWho | null; created_at: string; delivered_at: string | null; run_id: number | null
}
export type MailThreadInfo = {
  id: number; subject: string; status: 'open' | 'paused' | 'done'; paused_reason: string; started_by: MailWho | null
  parent_id: number | null; messages: number; cost_usd: number; agents: MailWho[]; created_at: string; updated_at: string
}
export type Mailbox = {
  inbox: Letter[]; done: Letter[]; waiting: Letter[]; threads: MailThreadInfo[]; colonies: MailWho[]
  mayor: MailWho | null; mayor_checked_at: string | null
}
/** A colony's lead coming to see you on the map: a question (or a paused thread of theirs) or news */
export type MailVisit = { agent_id: number; kind: 'ask' | 'fyi'; text: string; mail_ids: number[] }
/** A colony's post office: mail waiting for the colony to be woken, and its threads still going */
export type PostCount = { waiting: number; threads: number }
/** The new messages a mail event handed an agent, for showing in its chat */
export type MailSaid = { from: string; thread_id: number; subject: string; body: string }

/** One agent as a conversation in the chat app (backend/app/routers/chat.py) */
export type Conversation = {
  agent: AgentRef & { description: string; team: number[] }
  last: ChatMessage | null; waiting: number; status: RunStatus | null
}
/** Something said with an agent, in any of its chats or routines; routine: its name, if a routine said it */
export type ChatMessage = RunEvent & { run_id: number; routine: string | null }
export type Thread = { messages: ChatMessage[]; run: Run | null; mail: RunEvent[]; cursor: number; more: boolean }

export type SharedFile = FileStat & { content?: string }

export type ImportFile = { path: string; content: string }
export type ImportPlan = {
  agents: {
    source: string; name: string; description: string; exists: boolean; files: { source: string; path: string }[]
    alternatives: { source: string; kind: 'agent' | 'command'; lines: number }[]; team: string[]
  }[]
  shared: { source: string; path: string }[]
  skipped: { path: string; reason: string }[]
  needs_main: boolean; candidates: string[]
}

export type MarketAgent = {
  slug: string; name: string; description: string; tags: string[]; author: string; color: string; building: string
  tools: string[]; team: string[]; ask: string[]; files: number; lines: number; installed: boolean
}

export type GoogleStatus = {
  configured: boolean; app_url: string
  accounts: {
    id: number; email: string; status: 'connected' | 'expired'; apps: ('gmail' | 'calendar')[]
    index: { on: boolean; synced_at: string | null; people: number; problem: string }   // who they email, metadata only
  }[]
}

export type LinkedInStatus = {
  configured: boolean; app_url: string
  accounts: { id: number; email: string; status: 'connected' | 'expired'; expires_at: string | null }[]
}

export type City = {
  me: User | null; public: Share[]; agents: MyAgent[]; connections: Connection[]; shared_files: SharedFile[]
  town: Record<string, [number, number]>             // buildings you moved: key → top-left corner, tiles from its area's corner
  map_style: string                                  // how your map looks, kept with your account ("" = not chosen there)
  empty_colonies: EmptyColony[]                      // colonies you named before putting agents in
}

export type EmptyColony = { name: string; about: string }

/** What the caretaker asks the browser to do: show a building, switch the map's look, or offer a screen */
export type CaretakerAction =
  | { type: 'focus'; key: string }
  | { type: 'theme'; style: string }
  | { type: 'open'; screen: string; label: string; agent_id?: number }
/** One message to the caretaker and what it did (backend/app/caretaker.py) */
export type CaretakerTurn = {
  id: number; text: string; reply: string; actions: CaretakerAction[]; created_at: string
  state: 'done' | 'working' | 'failed'               // working: its sandbox is still on it (on a Claude subscription)
  changed: boolean; undone: boolean; can_undo: boolean
  proposals: RunEvent[]                              // agents and colonies it proposed, each waiting for your Add
}
/** A building as the map drew it, for the caretaker: top-left corner and size, in tiles from the square */
/** What the caretaker is shown of the map, in tiles from the square: each area (a colony's block, or the
 *  square: its box, corner and room) and each building, with the area it's in. */
export type MapBuilding = { key: string; kind: string; label: string; x: number; y: number; w: number; h: number
  area?: string; corner?: [number, number]; room?: [number, number, number, number] }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

/** Fired on `window` when a call answers 401 outside signing in: the session expired (hooks.ts listens). */
export const UNAUTHENTICATED = 'agenttown:unauthenticated'

const TIMEOUT = 30_000          // a normal call; reading a web page or importing a folder can take longer
const SLOW = 120_000

const isNetwork = (e: unknown) => e instanceof TypeError || (e instanceof Error && e.name === 'AbortError')

async function call<T>(method: string, path: string, body?: unknown, timeout = TIMEOUT): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
      signal: AbortSignal.timeout(timeout),
    })
  } catch (e) {
    // a hung server and a dead network look the same to the person: say so in words, and keep the kind
    const err = new Error(e instanceof Error && e.name === 'TimeoutError' ? 'Agent Town didn\'t answer in time. Try again.' : 'Can\'t reach Agent Town.')
    err.name = 'AbortError'
    throw err
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const d = data?.detail
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((e: { msg: string; loc?: string[] }) =>
      `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('; ') : `HTTP ${res.status}`
    if (res.status === 401 && !path.startsWith('/api/auth/')) window.dispatchEvent(new Event(UNAUTHENTICATED))
    throw new ApiError(res.status, msg)
  }
  return data as T
}

/** A read that may retry once if the network dropped, not if the server said no */
async function retrying<T>(fn: () => Promise<T>): Promise<T> {
  try { return await fn() } catch (e) { if (!isNetwork(e)) throw e }
  await new Promise(r => setTimeout(r, 800))
  return fn()
}

export const api = {
  city: () => retrying(() => call<City>('GET', '/api/city')),
  signup: (email: string, username: string, password: string, assistant_name: string) =>
    call<User>('POST', '/api/auth/signup', { email, username, password, assistant_name, starter: true }),
  authOptions: () => call<{ google: boolean; password_signup: boolean }>('GET', '/api/auth/options'),
  login: (login: string, password: string) => call<User>('POST', '/api/auth/login', { login, password }),
  logout: () => call('POST', '/api/auth/logout'),

  createAgent: (markdown: string, name: string | null, files: { path: string; content: string }[]) =>
    call<MyAgent>('POST', '/api/agents', { markdown, name: name || null, files }),
  updateAgent: (id: number, patch: Partial<Pick<MyAgent, 'name' | 'description' | 'color' | 'can_use_public' | 'model' | 'thinking' | 'model_credential_id' | 'building' | 'memory' | 'email_policy' | 'post_policy' | 'colony_name' | 'colony_about'>>) =>
    call<MyAgent>('PATCH', `/api/agents/${id}`, patch),
  deleteAgent: (id: number) => call('DELETE', `/api/agents/${id}`),
  putFile: (id: number, path: string, content: string) => call<MyAgent>('PUT', `/api/agents/${id}/files`, { path, content }),
  deleteFile: (id: number, fileId: number) => call<MyAgent>('DELETE', `/api/agents/${id}/files/${fileId}`),
  setGrants: (id: number, grants: Grant[]) => call<MyAgent>('PUT', `/api/agents/${id}/grants`, { grants }),
  setTeam: (id: number, member_ids: number[]) => call<MyAgent>('PUT', `/api/agents/${id}/team`, { member_ids }),
  manifest: (id: number) => call<unknown>('GET', `/api/agents/${id}/manifest`),

  addConnection: (body: NewConnection) => call<Connection>('POST', '/api/mcp', body),
  importConnections: (text: string) =>
    call<{ added: (Connection & { warnings: string[] })[]; problems: { name: string; detail: string }[] }>('POST', '/api/mcp/import', { text }),
  updateConnection: (id: number, patch: Partial<Omit<NewConnection, 'transport'>>) =>
    call<Connection>('PATCH', `/api/mcp/${id}`, patch),
  signOutConnection: (id: number) => call<Connection>('POST', `/api/mcp/${id}/sign-out`),
  checkConnection: (id: number) => call<Connection>('POST', `/api/mcp/${id}/check`),
  deleteConnection: (id: number) => call('DELETE', `/api/mcp/${id}`),

  share: (body: { kind: 'agent' | 'file'; agent_id?: number; file_id?: number; note?: string; allow_agent_use?: boolean }) =>
    call<Share>('POST', '/api/public', body),
  updateShare: (id: number, patch: { note?: string; allow_agent_use?: boolean; title?: string }) =>
    call<Share>('PATCH', `/api/public/${id}`, patch),
  unshare: (id: number) => call('DELETE', `/api/public/${id}`),
  getShare: (id: number) => call<Share>('GET', `/api/public/${id}`),

  sharedFile: (id: number) => call<SharedFile & { content: string }>('GET', `/api/files/${id}`),
  putSharedFile: (path: string, content: string) => call<SharedFile>('PUT', '/api/files', { path, content }),
  readPage: (url: string) => call<{ url: string; title: string; text: string }>('POST', '/api/files/read-page', { url }, SLOW),
  deleteSharedFile: (id: number) => call('DELETE', `/api/files/${id}`),
  previewImport: (files: ImportFile[], main?: string, choices?: Record<string, string>) =>
    call<ImportPlan>('POST', '/api/import/preview', { files, main, choices }, SLOW),
  doImport: (body: { files: ImportFile[]; agents: { source: string; name: string; files: string[]; team: string[] }[]; shared: string[] }) =>
    call<{ created: MyAgent[]; updated: MyAgent[]; shared: number }>('POST', '/api/import', body, SLOW),

  awake: () => call<{ agent_id: number; run_id: number; status: RunStatus }[]>('GET', '/api/runs/active'),
  activeRun: (agentId: number) => call<Run | null>('GET', `/api/agents/${agentId}/runs/active`),
  market: () => call<MarketAgent[]>('GET', '/api/marketplace'),
  installStarter: (assistant_name: string) => call<{ agent: MyAgent }>('POST', '/api/marketplace/starter', { assistant_name }),
  installMarket: (slug: string) => call<{ agent: MyAgent; added: string[] }>('POST', `/api/marketplace/${encodeURIComponent(slug)}/install`),

  googleStatus: () => call<GoogleStatus>('GET', '/api/connect/google'),
  disconnectGoogle: (id: number) => call('DELETE', `/api/connect/google/${id}`),
  linkedinStatus: () => call<LinkedInStatus>('GET', '/api/connect/linkedin'),
  disconnectLinkedIn: (id: number) => call('DELETE', `/api/connect/linkedin/${id}`),
  conversations: () => call<Conversation[]>('GET', '/api/conversations'),
  thread: (agentId: number, q: { after?: number; before?: number } = {}) =>
    call<Thread>('GET', `/api/agents/${agentId}/messages?${new URLSearchParams(Object.entries(q).map(([k, v]) => [k, String(v)]))}`),
  pushKey: () => call<{ key: string }>('GET', '/api/push/key'),
  subscribePush: (sub: PushSubscriptionJSON) => call('POST', '/api/push/subscriptions', sub),
  unsubscribePush: (endpoint: string) => call('DELETE', '/api/push/subscriptions', { endpoint }),
  testPush: () => call('POST', '/api/push/test'),
  setEmailIndex: (id: number, on: boolean) => call('PATCH', `/api/connect/google/${id}`, { index: on }),

  startRun: (agentId: number, message?: string) => call<Run>('POST', `/api/agents/${agentId}/runs`, message ? { message } : undefined),
  runEvents: (id: number, after: number) => call<{ run: Run; events: RunEvent[] }>('GET', `/api/runs/${id}/events?after=${after}`),
  sendMessage: (id: number, text: string) => call<RunEvent>('POST', `/api/runs/${id}/messages`, { text }),
  stopRun: (id: number) => call<Run>('DELETE', `/api/runs/${id}`),
  decideEmail: (id: number, eventId: number, send: boolean) => call<RunEvent>('POST', `/api/runs/${id}/approvals/${eventId}`, { send }),

  today: () => call<Today>('GET', '/api/today'),
  mailbox: (agentId?: number) => call<Mailbox>('GET', agentId ? `/api/mail?agent_id=${agentId}` : '/api/mail'),
  mailTown: () => call<{ visits: MailVisit[]; posts: Record<string, PostCount> }>('GET', '/api/mail/town'),
  mailThread: (id: number) => call<MailThreadInfo & { mail: Letter[] }>('GET', `/api/mail/threads/${id}`),
  sendMail: (body: { to: string; body: string; subject?: string; thread_id?: number }) => call<Letter>('POST', '/api/mail/send', body),
  answerMail: (id: number, answer: string) => call<Letter>('POST', `/api/mail/${id}/answer`, { answer }),
  readMail: (id: number) => call<Letter>('POST', `/api/mail/${id}/read`),
  deliverMail: (id: number) => call<Letter>('POST', `/api/mail/${id}/deliver`),
  finishThread: (id: number) => call<MailThreadInfo>('POST', `/api/mail/threads/${id}/finish`),
  addRoutine: (body: RoutineIn) => call<Routine>('POST', '/api/routines', body),
  updateRoutine: (id: number, patch: RoutineIn) => call<Routine>('PATCH', `/api/routines/${id}`, patch),
  deleteRoutine: (id: number) => call('DELETE', `/api/routines/${id}`),
  runRoutine: (id: number) => call<Run>('POST', `/api/routines/${id}/run`),

  caretaker: () => call<{ ready: boolean; why: string; via: '' | 'api_key' | 'subscription'; model: string; turns: CaretakerTurn[] }>('GET', '/api/caretaker'),
  askCaretaker: (text: string, layout: MapBuilding[], theme: string) =>
    call<{ turns: CaretakerTurn[] }>('POST', '/api/caretaker/messages', { text, layout, theme }),
  undoCaretaker: (turnId: number) => call<{ turns: CaretakerTurn[] }>('POST', `/api/caretaker/turns/${turnId}/undo`),
  decideCaretaker: (turnId: number, index: number, add: boolean) =>
    call<{ turns: CaretakerTurn[] }>('POST', `/api/caretaker/turns/${turnId}/proposals/${index}`, { add }),
  restartCaretaker: () => call<{ turns: CaretakerTurn[] }>('POST', '/api/caretaker/start-over'),
  setEmptyColonies: (colonies: EmptyColony[]) => call<{ empty_colonies: EmptyColony[] }>('PUT', '/api/account/empty-colonies', { colonies }),
  setPreferences: (prefs: { map_style?: string }) => call<{ map_style: string }>('PATCH', '/api/account/preferences', prefs),
  setTown: (positions: City['town']) => call<{ town: City['town'] }>('PUT', '/api/account/town', { positions }),
  deleteAccount: (confirm: { password?: string; username?: string }) => call('DELETE', '/api/account', confirm),
  rename: (username: string) => call<User>('PATCH', '/api/account/username', { username }),
  tokens: () => call<ApiToken[]>('GET', '/api/account/tokens'),
  createToken: (name: string, expires_days: number | null) =>
    call<ApiToken & { token: string }>('POST', '/api/account/tokens', { name, expires_days }),
  revokeToken: (id: number) => call('DELETE', `/api/account/tokens/${id}`),
  credentials: () => call<{ allow_subscription_tokens: boolean; credentials: Credential[] }>('GET', '/api/account/credentials'),
  addCredential: (body: { provider: Provider; kind: CredKind; label?: string; secret: string }) =>
    call<Credential>('POST', '/api/account/credentials', body),
  chatgptStart: () => call<{ handle: string; code: string; url: string; interval: number; expires_in: number }>('POST', '/api/account/credentials/chatgpt/start'),
  chatgptPoll: (handle: string) => call<{ pending: true } | { pending: false; credential: Credential }>('POST', '/api/account/credentials/chatgpt/poll', { handle }),
  checkCredential: (id: number) => call<Credential>('POST', `/api/account/credentials/${id}/check`),
  setDefaultCredential: (id: number) => call<Credential>('PATCH', `/api/account/credentials/${id}`, { is_default: true }),
  deleteCredential: (id: number) => call('DELETE', `/api/account/credentials/${id}`),
}
