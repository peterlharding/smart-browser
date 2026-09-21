// Build the browser: esbuild for the main process and the preloads, Vite for the UI
// (ADR 0015). One script instead of electron-vite, which would hold Vite at 7.
//
//   node build.mjs          one build into out/
//   node build.mjs --watch  rebuild on change (the UI through Vite's watcher)

import { build as esbuild, context } from 'esbuild';
import { build as vite } from 'vite';

const watch = process.argv.includes('--watch');

// Node code for Electron's main process, and the preloads. Preloads run sandboxed, which
// means CommonJS and nothing but `electron` to require, so each is bundled whole.
const node = {
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node24',
  sourcemap: 'linked',
  external: ['electron'],
  logLevel: 'warning',
};

const targets = [
  { ...node, entryPoints: { index: 'src/main/index.ts' }, outdir: 'out/main', outExtension: { '.js': '.cjs' } },
  {
    ...node,
    entryPoints: { chrome: 'src/preload/chrome.ts', overlay: 'src/preload/overlay.ts' },
    outdir: 'out/preload',
    outExtension: { '.js': '.cjs' },
  },
];

if (watch) {
  for (const options of targets) await (await context(options)).watch();
} else {
  await Promise.all(targets.map((options) => esbuild(options)));
}

await vite({ configFile: 'vite.config.mts', build: { watch: watch ? {} : null } });
