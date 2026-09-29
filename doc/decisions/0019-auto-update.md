# 0019 - The browser updates itself, quietly

- **Date:** 2026-09-29
- **Status:** Accepted
- **Builds on:** [ADR 0018](0018-packaging-and-signing.md) (the signed app and the zip each release carries), [ADR 0016](0016-local-history-backend-on-action.md) (what the browser sends, and when)
- **Sketch:** [`m5-auto-update.md`](../m5-auto-update.md)

## Context

0.7.0 installs from a DMG, and nothing tells you when 0.8.0 exists.
Updating means noticing a release, downloading 136 MB and dragging the app across.

ADR 0018 chose the mechanism and shipped what it needs: `update-electron-app` against `update.electronjs.org`, Electron's free update service for public repositories.
Every requirement is already met — macOS, signed and notarized builds, a public repository, releases on GitHub, and a zip named by platform and architecture (checked 2026-09-29).
What is left is how it behaves.

One fact decides most of that: **Squirrel.Mac applies a downloaded update the next time the app starts, whether or not anything asks you to restart.**
`quitAndInstall()` only makes it sooner.
So an update can arrive without interrupting anything and still be there tomorrow.

## Decision

### The service, named explicitly

`update-electron-app` against `update.electronjs.org`, with the repository given in the call (`peterlharding/smart-browser`) rather than through a new `repository` field in `apps/browser/package.json`.
The call site is where a reader asks the question, and the field is not otherwise used.

### It updates quietly

**No modal dialog** (`notifyUser: false`).
The browser reports a ready update where it reports everything else it knows:

- **The app menu's first item becomes "Restart to Update to 0.8.0"**, above Settings, and only while an update is waiting.
- **The toolbar's settings button carries a small dot.**
- Either one restarts into the new version.
- Ignore both, and the update is applied at the next launch.

A modal over a page you are reading, to announce something that will happen by itself, is the wrong trade.

### It checks at launch, then every six hours

The module's default is every ten minutes, and the minimum is five.
Six hours suits an app released every few days and a browser that stays open for days; the launch check covers the rest.

### It says what it sends, and can be turned off

Each check tells `update.electronjs.org` the app's version, platform and architecture.
That is a different service from the bookmarks API, and it is told nothing about pages, so ADR 0016's promise is untouched — but it is a request the browser makes on its own, so:

- **Settings gains "Check for updates automatically", on by default**, with a line saying what a check sends and to whom.
- **"Check for Updates Now" in the app menu**, which works whether or not the switch is on: turning off automatic checks should not mean giving up updates.
- Turning the switch off stops the periodic checks immediately.

### It never checks when it should not

- **Not in a development build.**
  A build run from the repo (`app.isPackaged` false) cannot update itself anyway.
- **Not under test.**
  The end-to-end suite runs the packaged app, so `SMART_BROWSER_NO_UPDATE` switches checking off and the test fixture sets it for every launch.
  The suite proves the app makes no such request rather than trusting that it does not.

### Failures are quiet too

A failed check is logged and left for the next one.
Nothing is shown: an update service that cannot be reached is not the user's problem to solve, and a browser that interrupts browsing to report it would be worse than one that says nothing.

### What can be tested, and what cannot

- **Unit** (an injected updater, no network): the states and what each shows, the interval, the switch stopping checks, and the refusal to check in a development build or under test.
- **End to end**: a packaged app with updates off makes no request to the service; the menu item and the Settings switch are where they should be.
- **Not automatable**: that Squirrel.Mac actually swaps the app.
  It needs two signed, notarized releases and the real service.
  `RELEASING.md` gets a recipe, run by hand once against 0.8.0: install 0.7.0, publish 0.8.0, open the old one, wait for the menu item, restart, check the version.
  **Until that has been done once, this feature is unproven**, and the release notes say so.

## Options not taken

- **The module's own dialog** (`notifyUser: true`).
  One line of code, and it interrupts whatever you are doing to announce something Squirrel would apply by itself at the next launch.
- **Silent, with no indication at all.**
  Cheapest, and you could not tell whether the version you are running has been superseded, nor ask for an update when you want one.
- **Checking every ten minutes**, the module's default.
  Forty times a day for an app released weekly.
- **`electron-updater` with its own feed.**
  ADR 0018 weighed it; it belongs to the electron-builder world this project deliberately left.
- **Self-hosted updates** (S3 or similar static storage, which the module also supports).
  Somewhere to pay for and keep up, to serve the releases GitHub already serves.
- **No switch, on the grounds that the check is harmless.**
  It is a request the browser makes without being asked; that it is small is not a reason to make it unrefusable.
- **Rollback.**
  The service serves the latest release, so recovering from a bad one means releasing again — the same as today, only faster.

## Consequences

- The browser reaches `update.electronjs.org` at launch and every six hours, until the switch is turned off.
- An update usually arrives the same day it is released, applied the next time the browser starts.
- A release that forgets its zip is invisible to the service: it shows as "no updates" rather than as a broken install, so `RELEASING.md` gains a check that the zip is attached.
- Intel Macs are still not served, since no such build exists.
- The DMG remains how a first install happens.

## Implementation notes

Where building it refined the decision above.

- **Electron's `autoUpdater` directly, not `update-electron-app`.**
  The module checks the moment it is called and its `stopUpdates` only clears the interval, so it cannot express two things this ADR requires: no check at all while the switch is off, and a manual check that still works then.
  Calling it again on re-enabling would also stack its listeners.
  What it does beyond that is the dialog this ADR rejects, the interval this ADR sets itself, and one line turning `owner/repo` into a feed URL.
  The service, and everything ADR 0018 published for it, is unchanged: `https://update.electronjs.org/<repo>/<platform>-<arch>/<version>`, with a User-Agent naming this browser.
  `updates.ts` is about a hundred lines, takes the updater as a parameter, and is unit-tested without a network or a packaged app.
- **The feed is set even when automatic checking is off**, which asks the service nothing and is what makes Check for Updates Now work in that state.
- **A ready update survives the switch being turned off**: what is already downloaded is applied at the next launch whatever the switch says, so hiding it would be a lie.
- **The tests assert the absence directly**: `autoUpdater.getFeedURL()` is empty in every end-to-end run, packaged or not, which is observable proof that no check could have been made.
- **The Settings switch is hidden in a build that cannot update itself**, rather than shown doing nothing.
