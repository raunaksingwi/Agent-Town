// The repo's own PRIVACY.md and TERMS.md, bundled at build time, so there's one copy of each.
// Google's consent screen needs these on the app's own domain: /privacy and /terms.
import privacy from '../../PRIVACY.md?raw'
import terms from '../../TERMS.md?raw'
import { Md } from './ui'

const LEGAL: Record<string, string> = { '/privacy': privacy, '/terms': terms }

export function Legal({ path }: { path: string }) {
  return <div className="legal">
    <a href="/">← Agent Town</a>
    <Md text={LEGAL[path]} />
  </div>
}
