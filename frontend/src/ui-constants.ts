// Numbers the screens share. CSS has the same bar height as --bar-h (index.css).

export const BAR_H = 70            // the top bar's height, px: panels and the camera start below it
export const SHEET_BP = 700        // at or under this width the dialogue is a bottom sheet, not a side column
export const PHONE_BP = 600        // at or under this width the top bar collapses into the ⋯ menu
export const NOTICE_MS = 8000      // how long a "Connected Gmail." notice stays

// how often each screen asks the server (ms); every poll pauses while the tab is hidden (hooks.ts)
export const POLL = {
  awake: 6000,          // the map: who's awake
  today: 15000,         // Today, when nothing runs
  todayBusy: 3000,      // Today, while a routine runs or an email is going out
  conversations: 10000, // the chat app's list
  workspace: 8000,      // the workspace's sidebar
  waiting: 5000,        // the chat app's Waiting screen
  chatLive: 1000,       // the dialogue, while the agent works
  chatIdle: 5000,       // the dialogue, once it has been quiet a while
  threadLive: 1500,     // the chat app's thread, while the agent is awake
  threadIdle: 8000,
}
export const STARTING_SLOW_MS = 90_000   // "starting" for longer than this: say so, and offer a way out

export const MIN_ZOOM = 0.25, MAX_ZOOM = 6

/** The person asked their system for less motion: no typewriter, no sparks, no idle couriers. */
export const reduceMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
