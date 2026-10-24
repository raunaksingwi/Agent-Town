import { defineConfig, searchForWorkspaceRoot } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs separately (uvicorn on :8000); Vite forwards /api to it,
// so the browser sees one origin and the session cookie just works.
// Another API port: AGENTTOWN_API=http://127.0.0.1:8010 npm run dev
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // legal.tsx bundles ../PRIVACY.md and ../TERMS.md; let the dev server read just those two
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), '../PRIVACY.md', '../TERMS.md'] },
    proxy: { '/api': { target: process.env.AGENTTOWN_API ?? 'http://127.0.0.1:8000', changeOrigin: false } },
  },
})
