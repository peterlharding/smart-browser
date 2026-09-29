# M5 — auto-update

> Sketch, not a decision.
> What updating itself takes now that releases carry a signed zip, what it would do to a browsing session, and the choices still open, so the ADR (0019) can be written from a settled list.
> Its recommendations were accepted on 2026-09-29 and drafted as [ADR 0019](decisions/0019-auto-update.md).

## Why now

0.7.0 installs from a DMG, and nothing tells you when 0.8.0 exists.
Every update means noticing a release, downloading a 136 MB disk image and dragging the app across.
That is the last thing keeping the browser from being something you simply use.

ADR 0018 already chose the mechanism and shipped what it needs: **`update-electron-app` against `update.electronjs.org`**, Electron's free update service for public GitHub repositories.
This sketch is about the behaviour, not the mechanism.

## What is already in place

Everything the service asks for, checked against its requirements on 2026-09-29:

| Requirement | State |
| --- | --- |
| Runs on macOS | Yes, `arm64` |
| Builds code signed | Yes: Developer ID, notarized and stapled (ADR 0018) |
| Public GitHub repository | Yes, `peterlharding/smart-browser` |
| Builds published to GitHub Releases | Yes, since 0.7.0 |
| A `.zip` of the app, named by platform and architecture | Yes: `Smart-Browser-0.7.0-darwin-arm64.zip` |
| Squirrel.Mac in the bundle | Yes, Electron ships it |

One gap: **`apps/browser/package.json` has no `repository` field**, which is where the module looks for the repository by default.
Either the field is added or the repository is named in the call.

## How Squirrel.Mac behaves

Worth stating plainly, because it decides how loud this feature needs to be:

- The app asks the service for the latest release, compares versions, and downloads the zip in the background.
- **A downloaded update is applied the next time the app starts, whether or not it is asked to restart.**
  Nothing is lost by not interrupting you.
- `quitAndInstall()` only makes it happen sooner.
- A failed check is an event, not a crash; the next check tries again.

So an update can be entirely quiet and still arrive, usually the same day, the next time you quit for lunch.

## What is actually being decided

### 1. How loudly it tells you

- **A. The module's own dialog** (`notifyUser: true`, the default).
  A modal appears over whatever you are doing: "A new version has been downloaded. Restart the application to apply the updates." with Restart and Later.
  One line of code, and it interrupts browsing to announce something that will happen by itself anyway.
- **B. Quiet, with a way to act on it.**
  `notifyUser: false`, and the browser shows it where it shows everything else: the app menu's first item becomes **Restart to Update to 0.8.0**, and the toolbar's settings button carries a small dot.
  Clicking either restarts into the new version.
  If you ignore it, the update is there tomorrow.
- **C. Silent.**
  Nothing at all; the update lands at the next launch.
  Cheapest, and you would never know a version you are running has been superseded.

B is the recommendation: it matches how the browser already reports things it knows (the save button, Saves Waiting), and it respects a session in progress.

### 2. How often it asks

The module's default is every 10 minutes, with a minimum of 5.
For an app released every few days that is a lot of requests for nothing.
**At launch, then every 6 hours**, is the recommendation: a browser tends to stay open for days, so the interval matters more than the launch check.

### 3. What leaves the machine

Each check is a request to `update.electronjs.org` carrying the app's version, platform and architecture.
That is a third party learning when this browser runs, at most four times a day.

ADR 0016's promise — that browsing tells the bookmarks API nothing — is untouched: this is a different service, told nothing about pages.
But the browser should say so plainly rather than have it discovered, and there should be a way to turn it off: **a Settings switch, "Check for updates automatically", on by default**, and **Check for Updates Now** in the app menu for a manual check either way.

### 4. What the tests must not do

The end-to-end suite runs the packaged app, which is exactly the app that checks for updates.
Left alone, every packaged test run would call the service, and CI's macOS job would too.
So updates are **off unless the app is packaged and not under test**: the fixture sets an environment variable the app honours, and the unit tests drive the update logic through an injected updater rather than the real one.

### 5. What is testable, and what is not

- **Unit**: version comparison, the menu item's text, the Settings switch, the interval, the decision not to check in a development build or under test.
- **End to end**: that a packaged app with updates switched off makes no request, and that the menu item and Settings switch are there.
- **Not automatable**: that Squirrel.Mac actually replaces the app.
  It needs two signed, notarized releases and a real service.
  The honest answer is a written recipe, run once by hand: release 0.8.0, open 0.7.0, watch it update.
  Until that is done, this feature is unproven, and the ADR should say so.

## Smaller questions

- **What if the release is broken?**
  There is no rollback: the service always serves the latest release.
  Recovering means publishing a further release, which is the same as the current DMG situation, only faster.
- **What about a release with no zip?**
  The service skips releases whose assets it cannot match, so a mistake in the release step shows up as "no updates", not as a broken install.
  `RELEASING.md` already attaches both files; a check that the zip is present belongs in the release step.
- **Intel Macs** are not built, so there is nothing to serve them.
  The service simply finds no matching asset.
- **The DMG stays** the way a first install happens.

## Recommendation

1. `update-electron-app` against `update.electronjs.org`, with the repository named in the call rather than a new `package.json` field.
2. Quiet notification (option B): the app menu's first item and a dot on the settings button, no modal.
3. Check at launch, then every 6 hours.
4. A Settings switch, on by default, and **Check for Updates Now** in the app menu.
5. Off in development builds, and off under test through an environment variable the fixture sets.
6. A written recipe in `RELEASING.md` for the one thing only a real release can prove, run once against 0.8.0.

## If that is chosen, the order of work

1. The ADR (0019), from this sketch and your answers.
2. `updates.ts` in the main process: the updater as a parameter, the interval, the states (idle, checking, downloaded, failed), and the switch that stops it; unit-tested with a fake updater.
3. The menu item and the Settings switch, and the dot on the settings button.
4. The end-to-end tests: no requests when updates are off; the menu item and switch are present.
5. `RELEASING.md`: the zip check and the manual recipe.
6. 0.8.0, then the recipe, by hand, once.
