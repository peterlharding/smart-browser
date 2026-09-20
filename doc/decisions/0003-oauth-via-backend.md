# 0003 — OAuth through the backend, not the desktop app

- **Date:** 2026-09-20
- **Status:** Accepted
- **Providers:** Google and GitHub initially

## Context

The browser needs user sign-in, via Google and GitHub. An Electron app is a *public* client:
anything shipped inside it — including an OAuth `client_secret` — is readable by anyone who
unpacks the asar. Two provider-specific facts constrain the design:

- **Google refuses OAuth in embedded user-agents.** Authorization must happen in the system
  browser or an approved native flow, not an Electron `BrowserWindow` pointed at the consent
  screen. This is enforced, not advisory.
- **GitHub added PKCE support in July 2025**, S256 only. But the announcement states GitHub
  "does not distinguish between public and confidential clients" and does not say a public
  client may omit the `client_secret` at token exchange. So PKCE alone does not make a
  secret-free desktop flow safe to assume for GitHub.

## Decision

**The FastAPI backend is the confidential OAuth client.** The Electron app never holds a
provider secret and never receives a provider token.

1. The app opens the **system browser** (`shell.openExternal`) at
   `/api/v2/auth/{provider}/start`, having first bound a loopback listener on
   `127.0.0.1:<ephemeral>`.
2. The backend generates PKCE `code_verifier`/`code_challenge` (S256) and a `state`, stores
   them server-side against the pending sign-in, and redirects to the provider.
3. The provider redirects to the backend's registered callback. The backend verifies `state`,
   exchanges the code using its own `client_secret` **and** the PKCE verifier, and reads the
   identity.
4. The backend mints its **own** short-lived access JWT plus a rotating refresh token, and
   redirects to the app's loopback URL carrying a one-time code the app exchanges for them.
5. The app stores the refresh token in the OS keychain via Electron `safeStorage` — never in
   `localStorage`, never on disk in the clear.

Identity is keyed on `(provider, provider_subject)` — Google's `sub`, GitHub's numeric user
id. **Never on email.**

## Consequences

**Good.** One auth path for both providers regardless of their differing public-client rules.
Provider secrets stay server-side. Provider tokens never reach the desktop. Adding a third
provider is backend-only. The same backend session works for the extensions at M6.

**Bad.** Sign-in requires the backend to be reachable — no offline first-login. The backend
now owns token rotation, revocation and refresh-token theft detection, which is real work.

**Watch — account linking.** Do not auto-link a Google and a GitHub identity because their
emails match. Provider emails can be unverified or changed, and match-on-email linking is a
known pre-account-takeover path: an attacker registers an account under a victim's email at
one provider and inherits the victim's account when they later sign in at the other. Linking
a second identity must be an explicit action taken while already signed in.

**Watch.** `state` is CSRF protection and must be single-use and expiring. The loopback
handover code likewise — one use, seconds of validity.

## Rejected

- **PKCE public client in the app.** Clean for Google, unclear for GitHub, and it puts
  provider tokens on the desktop where the keychain is the only thing protecting them.
- **Device authorization flow.** Works for both and needs no loopback, but the code-entry
  step is poor UX in an app that *is* a browser.
- **Embedded `BrowserWindow`.** Blocked by Google outright.

## Sources

- [PKCE support for OAuth and GitHub App authentication — GitHub Changelog](https://github.blog/changelog/2025-07-14-pkce-support-for-oauth-and-github-app-authentication/)
- RFC 8252, *OAuth 2.0 for Native Apps*
