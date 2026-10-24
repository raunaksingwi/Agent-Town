import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'

// Each surface is its own bundle, loaded when its address is opened: the chat app on a phone never
// downloads the map, and the privacy page never downloads the chat
const App = lazy(() => import('./App.tsx'))
const ChatApp = lazy(() => import('./chatapp.tsx').then(m => ({ default: m.ChatApp })))
const Legal = lazy(() => import('./legal.tsx').then(m => ({ default: m.Legal })))
const Workspace = lazy(() => import('./work.tsx').then(m => ({ default: m.Workspace })))

// /chat is the phone app (installable, with notifications); everything else is the town
const chat = location.pathname === '/chat' || location.pathname.startsWith('/chat/')
if (chat) document.body.classList.add('chat-app')
const legal = ['/privacy', '/terms'].includes(location.pathname)   // legal.tsx
// /work is the workspace (work.tsx). Once you pick it, / opens it too (sign-ins come back to /), until you
// switch back to the town
const work = location.pathname === '/work' || location.pathname.startsWith('/work/')
let pref: string | null = null
try { pref = localStorage.getItem('agenttown.ui'); if (work) localStorage.setItem('agenttown.ui', 'work') } catch { /* private mode */ }
const toWork = location.pathname === '/' && pref === 'work'
if (toWork) location.replace('/work' + location.search)
if (work) document.body.classList.add('ws-body-root')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={null}>
      {toWork ? null : legal ? <Legal path={location.pathname} /> : chat ? <ChatApp /> : work ? <Workspace /> : <App />}
    </Suspense>
  </StrictMode>,
)

// The service worker makes the app installable and shows notifications (public/sw.js)
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { /* not on http, or blocked */ })
