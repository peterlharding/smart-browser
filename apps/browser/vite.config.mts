// The browser's own UI: the chrome (tab strip and toolbar), the overlay (save sheet,
// settings) and the history page. Loaded from files, with no dev server, so what runs is what was built.

import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
  root: here('src/ui'),
  base: './',
  // Everything the plugin needs is here; there is no svelte.config.js to look for.
  plugins: [svelte({ configFile: false })],
  resolve: {
    // One set of tag rules for both clients: the extension's, imported rather than copied.
    alias: { '@tagging': here('../extension/src/lib/tags.js') },
  },
  build: {
    outDir: here('out/ui'),
    emptyOutDir: true,
    target: 'chrome140',
    sourcemap: true,
    rollupOptions: {
      input: {
        chrome: here('src/ui/chrome.html'),
        overlay: here('src/ui/overlay.html'),
        history: here('src/ui/history.html'),
      },
    },
  },
});
