# Smart-Browser: the browser

The Electron shell ([ADR 0015](../../doc/decisions/0015-electron-shell.md)).
It browses like Chrome and saves like the extension: `⌘⇧B` opens the save sheet over the page, `⌘⇧S` saves without asking.
Where you have been is kept on this machine, in `history.db` in the profile, behind the History menu and `⌘Y` ([ADR 0016](../../doc/decisions/0016-local-history-backend-on-action.md)).
The API hears only about pages you act on.
A save made while the API is away waits and is delivered when it answers; File > Saves Waiting lists what is still to go ([ADR 0017](../../doc/decisions/0017-offline-save-queue.md)).

## Running it

```sh
make browser-install   # once, from the repo root: npm ci for the workspace
make browser-dev       # build and run
```

The first time it loads a page on the internet, the Mac's outbound firewall asks whether Electron may connect.
Answer it before assuming the browser is broken; an unanswered prompt looks like a page that never loads.

Open Settings (`⌘,`) and enter the API's address and a token, the token half of an `API_TOKENS` entry.
The address is where `make api-dev` listens: `API_HOST` and `API_PORT` from `.env`, `http://127.0.0.1:8000` by default.
The token is kept in the Keychain through Electron's `safeStorage`, and never shown again.

Run from the repo, it uses its own profile, `~/Library/Application Support/Smart-Browser Dev`, so experiments never touch the installed app's history and settings.
`SMART_BROWSER_USER_DATA=/some/dir` names another, as the tests do.

## Packaging it

```sh
make browser-package            # Smart-Browser.app in apps/browser/dist/, signed ad hoc, to try
make test-browser-e2e-packaged  # the whole end-to-end suite, against that package
make browser-release            # signed with Developer ID, notarized: the DMG and zip a release carries
```

`package.mjs` does the packaging with Electron's own tools ([ADR 0018](../../doc/decisions/0018-packaging-and-signing.md)); RELEASING.md has the one-time signing and notarization setup.
The icon is `assets/icon.svg`, drawn into `assets/icon.icns` by `npx electron assets/make-icon.cjs` when it changes.

## How it is put together

```text
src/main/      the main process: the window and its views, tabs, IPC, the API client, settings,
               history (history.ts, SQLite through node:sqlite) and the menu built from it,
               the connection to the API (connection.ts) and the save queue (queue.ts)
src/preload/   one bridge per kind of view, one function per request, never ipcRenderer
src/ui/        Svelte: Chrome.svelte (tab strip, toolbar), Overlay.svelte (save sheet, settings, saves waiting),
               History.svelte (the history page, smart://history/)
src/shared/    ipc.ts, the typed channel surface; api-types.ts, generated from the API contract
test/unit/     Vitest: the omnibox, the API client, settings, URLs, history and the save queue
test/e2e/      Playwright: the built app against the real API and a local site
```

A window holds three layers of view: the chrome across the top, the active tab below it, and the overlay, which is attached only while a card is open.
A page's view is drawn over the window's own content, which is why the save sheet is a view of its own rather than something the chrome draws.

The API client runs in the main process only, so the token never reaches a renderer.
The browser's own UI is served from `smart://ui/`, with a CSP that allows no network access; favicons reach it as `data:` URLs fetched by the main process.
The history page is a tab showing `smart://history/`, from the same files in the same session, with a bridge that offers history and nothing else.
Tag parsing and autocomplete are the extension's own `src/lib/tags.js`, imported rather than copied.

`src/shared/api-types.ts` is generated: `make api-openapi` rewrites it with the contract, and `make check` fails if it is stale.

## Testing

```sh
make browser-check      # type checks (tsc, svelte-check) and unit tests; part of make check
make test-browser-e2e   # build, then drive the app against the API on <DB_NAME>_test
```

The end-to-end run starts its own API on the test database with a throwaway token, and a local site, so it needs no network.
It refuses the real database, as `make test-pg` does.
Every checkpoint writes each layer of the window to `test-results/snapshots/`, for looking at the result rather than only asserting on it.
