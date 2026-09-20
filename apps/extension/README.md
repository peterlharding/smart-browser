# Smart-Browser Bookmarks (extension)

Save the current tab **with tags, at the moment you save it**.

This is the save sheet from `doc/architecture.md`, delivered as a browser extension rather
than waiting for the Electron shell at M5. It needs no browser to be built, and it fixes the
problem the audit actually found.

## Why this exists before the browser

Of 9,472 bookmarks in the existing corpus, 80.8% have no tags at all, and the 1,817 that do
average 1.44 tags each. The schema has always supported many tags per bookmark. What was
missing was a moment at which tagging was convenient: the old extension posts a URL and
nothing else, and tagging happened later, by hand, in a web form you had to go and find.

Nobody does that. So tagging has to happen at save time, and that is all this is.

## Install

Chrome or any Chromium browser, unpacked:

1. `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → select `apps/extension/src`
3. Open the extension's **Options** and set:
   - **API address** — `http://127.0.0.1:8000` for a local `make api-dev`, or your
     deployed host. No path; `/api/v2` is appended.
   - **API token** — one of the values in the server's `API_TOKENS`.
4. Click **Test connection**. It reports the API version, contract version and schema
   revision, so a server on the wrong contract is visible rather than mysterious.

## Use

| Shortcut | What happens |
| --- | --- |
| `⌘⇧B` / `Ctrl+Shift+B` | Open the save sheet — tag, then save |
| `⌘⇧S` / `Ctrl+Shift+S` | Quick save, no tagging, no popup |
| Right-click → Save to Smart-Browser | Save a page or a link target |

**The save sheet** tells you first whether the page is already saved, and if so which tags
it carries. Type tags separated by commas or spaces; `Tab` accepts the top suggestion,
`Enter` saves. Suggestions come from your existing 567-tag vocabulary ranked by how often
you have used each one, not alphabetically. Click a tag already on the page to remove it.

Opening the sheet performs a **lookup**, never a save. Merely pressing the shortcut and
changing your mind leaves nothing behind.

**Quick save** is the old behaviour, kept because sometimes you want the page and not the
decision. The badge flashes green when the page was already tagged and amber when it was
saved untagged — the amber is the point. It is a small reminder of how the backlog got to
7,655 items.

## What it does not do

- **No AI tag suggestions yet.** Those arrive with M4, once the corpus has been crawled and
  embedded. Until then, suggestions are your own vocabulary ranked by usage.
- **No offline queue.** If the API is unreachable, the save fails and says so. The Electron
  shell gets a proper queue; adding one here would mean duplicating it.
- **Chrome only, so far.** The manifest is MV3 and the code has no Chrome-specific APIs
  beyond `chrome.*` namespacing, so a Firefox build is mostly a manifest change — but it is
  untested there and not claimed.

## Security note

The API token is stored in `chrome.storage.sync`, which means it syncs to the browser
profile and anyone with access to that profile can read it. Issue this client its own token
rather than sharing one with other clients, so it can be revoked on its own.

## Development

```sh
make test-ext      # or: node --test apps/extension/test/*.test.js
```

The logic worth testing is deliberately kept out of the DOM: `src/lib/tags.js` is pure
functions, and `src/lib/api.js` takes `fetch` as a constructor argument. Both run under
`node --test` with no dependencies, no browser and no network — which is why the extension
adds nothing to `node_modules`.

The version in `src/manifest.json` is managed by `scripts/version.py` along with everything
else, with the prerelease suffix stripped because Chrome rejects it.
