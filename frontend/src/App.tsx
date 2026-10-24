import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type CaretakerAction, type City, type Conversation, type MailVisit, type MapBuilding, type PostCount, type RunStatus } from './api'
import { AgentView } from './agent'
import { LibraryCard, SharedAgentCard, SharedFilesCard, StationCard } from './cards'
import { brainLook } from './city/brain'
import { agentBuilding } from './city/kinds'
import { hex, layout, seedOf, type Thing } from './city/layout'
import { CityView } from './city/render'
import { AuthModal, NewAgentModal, NewToolModal } from './modals'
import { AccountModal } from './account'
import { AddModal } from './importer'
import { AppList, SetupModal } from './setup'
import { WelcomeModal } from './welcome'
import { TourModal } from './tour'
import { PROFILE_FILE, ProfileModal } from './profile'
import { ConnectAiModal } from './connect-ai'
import { LinkButton, Modal, modalsOpen, msg } from './ui'
import { TodayView } from './today'
import { ColoniesModal } from './colonies'
import { CaretakerPanel } from './caretaker'
import { PostOfficeCard, VisitModal } from './mailbox'
import { OfficeRooms } from './rooms'
import { LookContext, isLook, lookOf, useApplyLook, type Look } from './look'
import { SettingsModal, type SettingsScreen } from './settings'
import { isMayor, nice } from './colony'
import { forgetCredentials, invalidateCredentials, useCredentials, useNarrow, useGoogleReturn, usePoll, useSignInReturn, useUnauthenticated, type Notice } from './hooks'
import { PHONE_BP, POLL, SHEET_BP } from './ui-constants'

export default function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const viewRef = useRef<CityView | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const [city, setCity] = useState<City | null>(null)
  const [down, setDown] = useState<string | null>(null)          // the API couldn't be reached: why
  const [sel, setSel] = useState<string | null>(null)             // the selected building's key
  const signin = useGoogleReturn()
  const [modal, setModal] = useState<'login' | 'signup' | 'add' | 'agent' | 'tool' | 'account' | 'apps' | 'profile' | 'ai' | 'colonies' | 'settings' | null>(signin.error ? 'login' : null)
  const [setupId, setSetupId] = useState<number | null>(null)   // "Make it your own" for this agent
  const [menu, setMenu] = useState(false)
  const [setupStep, setSetupStep] = useState(0)
  const [notice, setNotice] = useState<Notice>(null)
  const [editing, setEditing] = useState(false)                 // moving buildings around
  const [welcome, setWelcome] = useState<boolean | null>(null)   // null: not decided yet for this town
  const [tour, setTour] = useState(false)                       // how the town works: after sign-up, then from the menu
  const [houseOpen, setHouseOpen] = useState(false)             // inside an agent's house
  const [aiVersion, setAiVersion] = useState(0)                  // bumped when an AI account changes, so the caretaker looks again
  const { creds } = useCredentials()
  const hasAi = creds === null ? null : creds.length > 0         // any AI account yet? null: don't know
  const phone = useNarrow(PHONE_BP)
  // Home is Today (what your agents did, what's waiting on you); the town is where you go to talk to them
  const [view, setViewState] = useState<'today' | 'town'>(() => {
    try { return localStorage.getItem('agenttown.view') === 'town' ? 'town' : 'today' } catch { return 'today' }
  })
  const setView = (v: 'today' | 'town') => { setViewState(v); try { localStorage.setItem('agenttown.view', v) } catch { /* private mode */ } }

  useSignInReturn(setNotice, id => { setSetupStep(1); setSetupId(id) })
  const [refit, setRefit] = useState(true)
  // the map's look: kept with your account (so the caretaker can change it too), else this browser's choice
  const [localTheme, setLocalTheme] = useState<Look>(() => {
    try { const t = localStorage.getItem('agenttown.theme'); if (isLook(t)) return t } catch { /* private mode */ }
    return 'retro'
  })
  const [helping, setHelping] = useState(false)                 // the caretaker's panel is open

  const reload = useCallback(async () => {
    try { setCity(await api.city()); setDown(null) } catch (e) { setDown(msg(e)) }
  }, [])
  useEffect(() => { reload() }, [reload])
  // the session cookie expired while this was open: say so, and offer the sign-in
  useUnauthenticated(() => {
    if (!city?.me) return
    forgetCredentials(); setSel(null); setSetupId(null); setHelping(false)
    setNotice({ ok: false, text: 'Your session expired. Sign in again.' })
    setModal('login')
    reload()
  })

  useEffect(() => {
    const v = new CityView(canvasRef.current!)
    viewRef.current = v
    return () => v.destroy()
  }, [])

  const theme: Look = isLook(city?.map_style) ? lookOf(city?.map_style) : localTheme
  useEffect(() => { if (theme !== 'office') viewRef.current?.setTheme(theme) }, [theme])   // the Office has no map
  useApplyLook(theme)                                              // the look styles the whole page, not just the map
  const pickTheme = (n: Look) => {
    setLocalTheme(n)
    try { localStorage.setItem('agenttown.theme', n) } catch { /* private mode */ }
    if (city?.me) {
      setCity({ ...city, map_style: n })
      api.setPreferences({ map_style: n }).catch(e => setNotice({ ok: false, text: `Couldn't save the map style: ${msg(e)}` }))
    }
  }

  useEffect(() => { viewRef.current?.setPlayerName(city?.me ? `@${city.me.username}` : 'you') }, [city?.me])

  // who's awake: lanterns, z's and NPCs on the map follow every agent's run, not just the open chat
  const signedIn = !!city?.me
  const [awake, setAwake] = useState<Map<number, RunStatus>>(new Map())   // the same, for the Office's rooms
  usePoll(() => api.awake().then(a => { viewRef.current?.setStatuses(a); setAwake(new Map(a.map(x => [x.agent_id, x.status]))) }, () => {}),
    () => POLL.awake, [city], signedIn)
  // mail on the map: post offices' flags, and the leads who walk to the square to see you (mailbox.tsx)
  const [visit, setVisit] = useState<number | null>(null)
  const visiting = useRef<Set<number>>(new Set())
  const [mail, setMail] = useState<{ visits: MailVisit[]; posts: Record<string, PostCount> }>({ visits: [], posts: {} })
  const loadMail = useCallback(() => api.mailTown().then(m => {
    visiting.current = new Set(m.visits.map(v => v.agent_id))
    viewRef.current?.setMail(m.visits, m.posts)
    setMail(m)
  }, () => {}), [])
  usePoll(loadMail, () => POLL.awake, [city], signedIn)
  // the mayor walks beside you: M (or a click) opens its chat, or what it has for you if it's waiting on you
  const mayor = city?.me ? city.agents.find(isMayor) : undefined
  const [mayorOpen, setMayorOpen] = useState(false)
  const openMayor = useCallback(() => { setSel(null); setView('town'); setMayorOpen(true) }, [])
  useEffect(() => {
    const v = viewRef.current
    if (!v) return
    v.onVisit = setVisit
    v.onCompanion = () => { if (mayor && visiting.current.has(mayor.id)) setVisit(mayor.id); else openMayor() }
    v.setCompanion(mayor ? { id: mayor.id, name: mayor.name, look: { color: hex(mayor.color), seed: seedOf(mayor.slug),
      role: agentBuilding(mayor), brain: brainLook(mayor.brain) } } : null)
  }, [mayor, openMayor])

  const office = theme === 'office'                                // the Office isn't a map: it's meeting rooms (rooms.tsx)
  const L = useMemo(() => (city ? layout(city) : null), [city])
  const rooms = office && !!city && !(city.me && view === 'today' && !sel)
  // what each agent last said and what waits for your OK: the line on its seat in the Office
  const [convs, setConvs] = useState<Conversation[]>([])
  usePoll(() => api.conversations().then(setConvs, () => {}), () => POLL.awake, [city], signedIn && rooms)
  const [focus, setFocus] = useState<string | null>(null)        // the caretaker pointed at something in the Office
  useEffect(() => { viewRef.current?.setPaused(office) }, [office])   // the Office never shows the map, not even behind Today
  useEffect(() => {
    if (!L || !viewRef.current) return
    viewRef.current.setLayout(L, refit)
    setRefit(false)
  }, [L]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const v = viewRef.current
    if (!v) return
    v.onSelect = (t: Thing | null) => { if (t) setMayorOpen(false); setSel(t ? t.key : null) }   // a building closes the mayor's chat
    v.setSelected(sel)
  }, [sel])

  // move mode: a dropped building stays where you put it (saved with your account, from its area's corner)
  useEffect(() => {
    const v = viewRef.current
    if (!v || !L) return
    v.setEditing(editing)
    v.onMove = (t, x, y) => {
      const corner = L.areas[t.area]?.corner
      if (!city || !corner) return
      const town = { ...city.town, [t.key]: [x - corner[0], y - corner[1]] as [number, number] }
      setCity({ ...city, town })
      api.setTown(town).catch(e => { setNotice({ ok: false, text: `Couldn't save where you moved it: ${e.message}` }); reload() })
    }
  }, [editing, city, L, reload])
  const resetTown = () => {
    if (!city || !confirm('Put every house back in its block?')) return
    setCity({ ...city, town: {} })
    api.setTown({}).catch(e => { setNotice({ ok: false, text: `Couldn't put them back: ${msg(e)}` }); reload() })
  }

  // Escape: a modal on top takes it first (ui.tsx), so this only sees it when nothing is open
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || modalsOpen()) return
      if (menu) setMenu(false); else if (editing) setEditing(false); else if (!modal && setupId === null && !helping) setSel(null)
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [modal, menu, setupId, editing, helping])
  // while a screen owns the keyboard, keys don't walk you around behind it
  useEffect(() => { viewRef.current?.setInputEnabled(!rooms && !modal && setupId === null && !welcome && !tour && !helping && !houseOpen) },
    [rooms, modal, setupId, welcome, tour, helping, houseOpen])

  // keep the selection valid after a reload (e.g. the agent was deleted)
  const thing = sel && L ? L.things.find(t => t.key === sel) : null
  useEffect(() => { if (sel && L && !thing) setSel(null) }, [sel, L, thing])

  // one of your agents: side panels (about + chat) instead of the bottom card
  const agent = city && thing?.kind === 'agent' ? city.agents.find(x => x.id === thing.id) : mayorOpen ? mayor : undefined
  const agentId = agent?.id
  const onStatus = useCallback((s: RunStatus | null) => { if (agentId) viewRef.current?.setAgentStatus(agentId, s) }, [agentId])
  const onTool = useCallback((server: string) => { if (agentId) viewRef.current?.sendCourier(agentId, server) }, [agentId])

  const card = (() => {
    if (!city || !thing || thing.kind === 'agent') return null
    const close = () => setSel(null)
    if (thing.kind === 'station') {
      const c = city.connections.find(x => x.id === thing.id)
      return c && <StationCard key={c.id} conn={c} reload={reload} onClose={close} />
    }
    if (thing.kind === 'post') {
      const lead = city.agents.find(x => x.id === thing.id)
      return lead && <PostOfficeCard key={lead.id} agentId={lead.id} colony={thing.sub ?? lead.name} onClose={close} />
    }
    if (thing.kind === 'files') return <SharedFilesCard files={city.shared_files} reload={reload} onClose={close} onProfile={() => setModal('profile')} />
    if (thing.kind === 'shared') {
      const s = city.public.find(x => x.id === thing.id)
      return s && <SharedAgentCard key={s.id} share={s} onClose={close} />
    }
    return <LibraryCard shares={city.public.filter(s => s.kind === 'file')} me={city.me?.username ?? null} reload={reload} onClose={close} />
  })()

  // talking happens in a column on the right (a bottom sheet on phones): keep the agent in the open space
  // beside it, and follow the panel as it grows or shrinks
  const hasCard = !!card, hasAgent = !!agent
  useEffect(() => {
    const v = viewRef.current
    if (!v) return
    const place = () => {
      const dlg = hasAgent ? document.querySelector('.dialogue') as HTMLElement | null : null
      const side = dlg && innerWidth > SHEET_BP
      v.setSideInsets(0, side ? dlg.offsetWidth + 12 : 0)
      v.setBottomInset(side ? 0 : dlg ? dlg.offsetHeight : cardRef.current?.offsetHeight ?? 0)
    }
    place()
    if (sel && (hasCard || hasAgent)) v.focusOn(sel)
    const watched = [document.querySelector('.dialogue'), cardRef.current].filter((el): el is HTMLElement => !!el)
    if (!watched.length || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(place)
    watched.forEach(el => ro.observe(el))
    return () => ro.disconnect()
  }, [sel, hasCard, hasAgent])

  const me = city?.me
  const onToday = !!me && view === 'today' && !thing
  // a new, empty town opens on the front door, once; "Get started" brings it back
  useEffect(() => { if (city && welcome === null && city.me) setWelcome(city.agents.length === 0) }, [city, welcome])
  // once there are agents but they don't know you yet: a gentle, dismissable nudge (never a form up front)
  const nudgeKey = `agenttown.profileNudge.${me?.username}`
  const [nudgeHidden, setNudgeHidden] = useState(false)
  const [nudgeOpen, setNudgeOpen] = useState(false)             // phones: the nudge is one line until tapped
  useEffect(() => { try { setNudgeHidden(!!me && localStorage.getItem(nudgeKey) === 'later') } catch { /* private mode */ } }, [nudgeKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const quiet = !!me && !!city && city.agents.length > 0 && !modal && setupId === null && !welcome && !onToday
  // one nudge at a time: an AI first (nothing works without it), then telling them about you
  const aiNudge = quiet && hasAi === false
  const nudge = quiet && hasAi !== false && !city.shared_files.some(f => f.path === PROFILE_FILE) && !nudgeHidden
  const connectAi = (fromSetup = false) => { if (fromSetup) setSetupStep(2); setModal('ai') }
  const later = () => { setNudgeHidden(true); try { localStorage.setItem(nudgeKey, 'later') } catch { /* private mode */ } }
  const setupAgent = setupId !== null ? city?.agents.find(a => a.id === setupId) : undefined
  // a new account from Google starts like one from the form: on its assistant's apps
  const startedNew = useRef(false)
  useEffect(() => {
    if (!signin.isNew || startedNew.current || !city?.me) return
    startedNew.current = true
    if (city.agents.some(isMayor)) { setRefit(true); openMayor() }
    setTour(true)
  }, [city]) // eslint-disable-line react-hooks/exhaustive-deps
  const aiChanged = () => { invalidateCredentials(); setAiVersion(v => v + 1) }

  // the caretaker: it's told where every building stands as drawn (it can't work out the layout itself),
  // and the browser does what it asks: show a building, or open a screen when you press its button
  // Each colony's block (and the square) is an area: its box, its corner, and its room, then the buildings in it
  const snapshot = useCallback((): MapBuilding[] => {
    if (!L) return []
    const [ox, oy] = L.origin, r = (n: number) => Math.round(n * 100) / 100
    const areas = Object.values(L.areas).map(a => {
      const d = L.districts.find(d => d.key === a.key), box = d ?? a.room
      return { key: a.key, kind: 'area', label: (d?.name ?? 'The town square').slice(0, 120),
        x: r(box.x - ox), y: r(box.y - oy), w: r(box.w), h: r(box.h), corner: [r(a.corner[0] - ox), r(a.corner[1] - oy)] as [number, number],
        room: [r(a.room.x - ox), r(a.room.y - oy), r(a.room.w), r(a.room.h)] as [number, number, number, number] }
    })
    const buildings = L.things.filter(t => /^((agent|station|shared):\d+|files|library)$/.test(t.key))
      .map(t => ({ key: t.key, kind: t.kind, label: t.label.slice(0, 120), area: t.area, x: r(t.x - ox), y: r(t.y - oy), w: r(t.w), h: r(t.h) }))
    return [...areas, ...buildings]
  }, [L])
  const caretakerDid = (actions: CaretakerAction[]) => {
    for (const a of actions) if (a.type === 'focus') {
      setSel(null); setView('town')
      if (office) setFocus(a.key); else viewRef.current?.focusOn(a.key)
    }
  }
  const SCREENS = { apps: 'apps', colonies: 'colonies', profile: 'profile', account: 'account', add: 'add' } as const
  const openScreen = (a: Extract<CaretakerAction, { type: 'open' }>) => {
    if (a.screen === 'setup' && a.agent_id) { setSetupStep(0); setSetupId(a.agent_id) }
    else if (a.screen === 'move') { setSel(null); setView('town'); setEditing(true); setHelping(false) }
    else if (a.screen === 'today') { setSel(null); setView('today') }
    else if (a.screen === 'connect_ai') connectAi()
    else if (a.screen in SCREENS) setModal(SCREENS[a.screen as keyof typeof SCREENS])
  }
  const canHelp = !!me && !agent && !editing
  const showHelp = canHelp && helping
  useEffect(() => {                        // keep what it shows you in the open space beside its panel
    const el = showHelp ? document.querySelector('.caretaker') as HTMLElement | null : null
    if (!el || innerWidth <= SHEET_BP) return
    viewRef.current?.setSideInsets(0, el.offsetWidth + 12)
    return () => viewRef.current?.setSideInsets(0, 0)
  }, [showHelp])

  const signOut = async () => {
    setMenu(false)
    try { await api.logout() } catch (e) { setNotice({ ok: false, text: `Couldn't sign out: ${msg(e)}` }); return }
    forgetCredentials(); setSel(null); setEditing(false); setWelcome(null); setRefit(true); reload()
  }
  const open = (m: NonNullable<typeof modal>) => { setMenu(false); setModal(m) }
  const settingsButton = <button className="item" onClick={() => open('settings')}
    title={me ? `Your look, account and AI, what agents know about you, ${office ? 'cabins' : 'colonies'} and apps` : 'How Agent Town looks'}>Settings</button>
  // a screen opened from Settings goes back to Settings when you close it; opened from anywhere else, it just closes
  const [fromSettings, setFromSettings] = useState<string | null>(null)
  const closeScreen = () => { setModal(fromSettings === modal ? 'settings' : null); setFromSettings(null) }
  const addAgents = me && <button className="primary" onClick={() => open('add')}>+ Add agents</button>
  const nudgeBox = (text: string, actions: React.ReactNode) => <div className={`nudge${phone && !nudgeOpen ? ' compact' : ''}`} role="status">
    <span className="nudge-text">{text}</span>
    {phone && !nudgeOpen ? <button className="x" aria-label="More" aria-expanded={false} onClick={() => setNudgeOpen(true)}>▾</button>
      : <span className="nudge-actions">{actions}</span>}
  </div>

  return (
    <LookContext.Provider value={theme}>
      <canvas ref={canvasRef} className={`city${office ? ' hidden' : ''}`} />
      {rooms && city && <div className={`or-wrap${agent || showHelp ? ' side' : ''}${card ? ' docked' : ''}`}>
        <OfficeRooms city={city} awake={awake} convs={convs} visits={mail.visits} posts={mail.posts} selected={sel} focus={focus}
          onOpen={key => { setMayorOpen(false); setSel(key) }} onMayor={openMayor} onVisit={setVisit} onColonies={() => setModal('colonies')} />
      </div>}
      <header className="bar">
        <h1>Agent Town</h1>
        {me && <div className="seg views" role="tablist">
          <button role="tab" aria-selected={view === 'today' && !thing} className={view === 'today' && !thing ? 'on' : ''}
            onClick={() => { setSel(null); setView('today') }}>Today</button>
          <button role="tab" aria-selected={view === 'town' || !!thing} className={view === 'town' || thing ? 'on' : ''}
            onClick={() => setView('town')}>{office ? 'Office' : 'Town'}</button>
        </div>}
        <span className="grow" />
        {me ? (!phone && addAgents) : <>
          <button onClick={() => setModal('login')}>Sign in</button>
          <button className="primary" onClick={() => setModal('signup')}>Create account</button>
        </>}
        {/* everything you open now and then lives in one menu under your name; the bar keeps the tabs and + Add agents */}
        <div className="menu-wrap">
          {me ? <button className="account" aria-label="Your menu" aria-expanded={menu} onClick={() => setMenu(!menu)}
            title="Your account, teams, apps and settings">
            <span className="avatar" aria-hidden>{me.username.slice(0, 1).toUpperCase()}</span>
            {!phone && <span className="account-name">{me.username}</span>}<span className="caret" aria-hidden>▾</span>
          </button> : <button className="more" aria-label="More" aria-expanded={menu} onClick={() => setMenu(!menu)}>⋯</button>}
          {menu && <div className="menu" onMouseLeave={() => !phone && setMenu(false)}>
            {me && phone && addAgents}
            {!office && <div className="menu-label">Map</div>}
            {!office && <button className="item" onClick={() => { viewRef.current?.fit(); setMenu(false) }}>Show the whole town</button>}
            {me && <button className="item" onClick={() => { setMenu(false); setTour(true) }}>How Agent Town works</button>}
            {me && !office && <button className="item" onClick={() => { setSel(null); setView('town'); setEditing(true); setMenu(false) }}>Move buildings</button>}
            {me && <>
              <div className="menu-label">Other layouts</div>
              <a className="item" href="/work" title="The same agents in a plain layout, without the map">Standard view</a>
              <a className="item" href="/chat" title="Agent Town as a chat app: install it on your phone for notifications">Chat app</a>
              <hr />
              {settingsButton}
              <button className="item" onClick={signOut}>Sign out</button>
            </>}
            {!me && settingsButton}
            <div className="menu-links"><a className="menu-link" href="/privacy" target="_blank" rel="noreferrer">Privacy policy</a>
              <a className="menu-link" href="/terms" target="_blank" rel="noreferrer">Terms of service</a></div>
          </div>}
        </div>
      </header>

      {down && !city && <div className="hello offline" role="alert">
        <b>Can't reach Agent Town.</b> {down}
        <div className="row tight"><button className="primary" onClick={reload}>Retry</button></div>
      </div>}
      {city && !me && !thing && <div className="hello">
        <b>Welcome to Agent Town.</b> Hand the boring tasks to your agents. Each one {office ? 'has a seat on its team' : 'lives in its own house'} and has one
        job, like sorting your inbox, planning your week, or chasing replies. You'll know every one of them by name.{' '}
        <LinkButton onClick={() => setModal('signup')}>Create an account</LinkButton> to build your own {office ? 'office' : 'town'}.
        <div className="hello-links"><a href="/privacy">Privacy policy</a> · <a href="/terms">Terms of service</a></div>
      </div>}
      {city && me && onToday && <TodayView city={city} hasAi={hasAi} onConnectAi={() => connectAi()} onGetStarted={() => setWelcome(true)}
        onChat={id => { setView('town'); setSel(`agent:${id}`) }} onTown={reload} />}
      {city && me && !onToday && city.agents.length === 0 && !thing && <div className="hello">
        <b>Your {office ? 'office' : 'town'} is empty.</b> <LinkButton onClick={() => setWelcome(true)}>Get started</LinkButton> with the
        mayor (it works out the agents you need and sets them up with you), or click <b>+ Add agents</b> to pick from the agent market or bring your own (a single <code>.md</code> file,
        or a whole folder like <code>.claude</code>). Then {office ? <>click an agent's card to chat.</> : <>walk up to one and press <b>E</b> to chat.</>}
      </div>}

      {editing && <div className="editing" role="status">
        <span><b>Moving buildings.</b> Drag any building to a new spot: green means it fits. Put similar ones together.</span>
        {city && Object.keys(city.town).length > 0 && <button onClick={resetTown}>Put everything back</button>}
        <button className="primary" onClick={() => setEditing(false)}>Done</button>
      </div>}
      {card && <div ref={cardRef} className="dock">{card}</div>}
      {visit !== null && <VisitModal agentId={visit} onClose={() => setVisit(null)} onDone={loadMail} />}
      {agent && city && <AgentView key={agent.id} agent={agent} city={city} reload={reload} onClose={() => { setSel(null); setMayorOpen(false) }}
        onStatus={onStatus} onTool={onTool} onHouse={setHouseOpen}
        onSetup={() => setSetupId(agent.id)} onConnectAi={() => connectAi()} />}
      {aiNudge && nudgeBox('🧠 Your team needs an AI to think with. Connect your Claude or ChatGPT account once, and they can all get to work.',
        <button className="primary" onClick={() => connectAi()}>Connect your AI</button>)}
      {nudge && nudgeBox('👋 Your agents work better when they know you. Share your website or bio once, and every one of them will.',
        <><button className="primary" onClick={() => setModal('profile')}>Tell them about you</button><button onClick={later}>Later</button></>)}
      {canHelp && !helping && <button className="ct-fab" onClick={() => setHelping(true)} title="Help: ask the caretaker"
        aria-label="Help">?</button>}
      {showHelp && <CaretakerPanel snapshot={snapshot} theme={theme} aiVersion={aiVersion} onActions={caretakerDid} onScreen={openScreen}
        onChanged={reload} onConnectAi={() => connectAi()} onClose={() => setHelping(false)} />}
      {notice && <div className={`notice ${notice.ok ? 'ok' : 'bad'}`} role="status">{notice.text}
        <button className="x" onClick={() => setNotice(null)} aria-label="Dismiss">×</button></div>}
      {setupAgent && city && !modal && <SetupModal key={`${setupAgent.id}:${setupStep}`} initialStep={setupStep} agent={setupAgent} city={city} reload={reload}
        onClose={() => { setSetupId(null); setSetupStep(0) }}
        onChat={() => { setSel(`agent:${setupAgent.id}`); setSetupId(null); setSetupStep(0) }}
        onAccount={() => connectAi(true)} onAdvanced={() => setModal('tool')} onProfile={() => setModal('profile')} />}
      {modal === 'settings' && <SettingsModal look={theme} onPick={pickTheme} onClose={() => setModal(null)}
        onOpen={me ? (s: SettingsScreen) => { setFromSettings(s); setModal(s) } : undefined} />}
      {modal === 'ai' && <ConnectAiModal onClose={() => setModal(null)} onDone={() => { setModal(null); aiChanged() }} />}
      {modal === 'profile' && city && <ProfileModal city={city} reload={reload} onClose={closeScreen} />}
      {modal === 'apps' && city && <Modal title="Connect your apps" onClose={closeScreen} wide>
        <p className="hint">Connect an app once; then choose, per agent, which ones it may use (in its panel, or in "Make it your own").</p>
        <AppList city={city} reload={reload} onAdvanced={() => setModal('tool')} />
      </Modal>}

      {welcome && city?.me && !modal && setupId === null && <WelcomeModal city={city} reload={reload} onClose={() => setWelcome(false)}
        onAdd={() => { setWelcome(false); setModal('add') }}
        onStart={() => { setRefit(true); setWelcome(false); openMayor() }} />}
      {tour && me && !modal && setupId === null && !welcome && <TourModal mayor={mayor && nice(mayor.name)} phone={phone}
        onClose={() => setTour(false)} />}
      {modal === 'colonies' && city?.me && <ColoniesModal city={city} reload={reload} onClose={closeScreen}
        onVisit={id => { setModal(null); setView('town'); setSel(`agent:${id}`) }} onAddAgents={() => setModal('add')} />}

      {(modal === 'login' || modal === 'signup') && <AuthModal mode={modal} error={signin.error} onClose={() => setModal(null)}
        onDone={async m => {
          setModal(null); setRefit(true); forgetCredentials()
          try {
            const c = await api.city()
            setCity(c); setDown(null)
            // a new account starts with only its mayor: open its chat, where it shows them round and builds their town with them
            if (m === 'signup' && c.agents.some(isMayor)) openMayor()
            if (m === 'signup') setTour(true)
          } catch (e) { setDown(msg(e)) }
        }} />}
      {modal === 'account' && me && <AccountModal me={me} onClose={() => { closeScreen(); aiChanged(); reload() }}
        onDeleted={() => { setModal(null); setSel(null); setSetupId(null); setWelcome(null); setRefit(true); forgetCredentials(); reload() }} />}
      {modal === 'add' && <AddModal onClose={() => setModal(null)} onWrite={() => setModal('agent')}
        onDone={async id => { setModal(null); setRefit(true); await reload(); if (id) setSel(`agent:${id}`) }} />}
      {modal === 'agent' && <NewAgentModal onClose={() => setModal(null)}
        onDone={async id => { setModal(null); setRefit(true); await reload(); setSel(`agent:${id}`) }} />}
      {modal === 'tool' && <NewToolModal onClose={() => setModal(null)}
        onDone={async id => { setModal(null); setRefit(true); await reload(); if (setupId === null) setSel(`station:${id}`) }} />}
    </LookContext.Provider>
  )
}
