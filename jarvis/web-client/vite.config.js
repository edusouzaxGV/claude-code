import { defineConfig } from 'vite';

// Minimal Vite config. The frontend is plain JS + a single HTML entry.
// The token server runs separately on port 3001 (see package.json scripts).
export default defineConfig({
  server: {
    port: 5173,
  },
});
