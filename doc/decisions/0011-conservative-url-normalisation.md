# 0011 - URL normalisation only merges spellings of the same resource

- **Date:** 2026-09-21
- **Status:** Accepted

## Context

`urlnorm.normalise()` does two jobs at once, and the second is the one that makes its mistakes expensive.

1. **It makes the identity.**
   `url_hash` is the SHA-256 of its output, and `UNIQUE (url_hash)` is the entire no-duplicates guarantee (ADR 0006).
2. **It makes the stored URL.**
   `bookmark.url` is its output, not what was saved.
   That is the link you open, the URL the crawler fetches, and the URL every later saver inherits.

So a rule that changes which resource a URL names does not merely merge two rows.
It rewrites your link into a different one, and it merges a second person's different page into the first person's row, where the second page is then unreachable.
A duplicate row costs a little tidiness and can be merged later.
A wrong merge loses the page and cannot be undone, because the original spelling was never stored.

The module states the right rule in its own docstring: "Normalisation that changes which page you land on is worse than a duplicate row, so when in doubt this leaves the URL alone."
Several of its rules break it.
Measured against the current code:

| Input | Output | What goes wrong |
| --- | --- | --- |
| `/docs/` | `/docs` | Different URLs; many servers serve different content or relative links resolve differently. The code comment says they "can differ" and then strips anyway. |
| `?a=2&a=1` | `?a=1&a=2` | Sorting reorders repeated keys, which are ordered lists to most frameworks. |
| `?b=2&a=1` | `?a=1&b=2` | Harmless for most servers, and not for all; the gain is unmeasured. |
| `/wiki?edit` | `/wiki?edit=` | A bare key and an empty value are different to some servers. |
| `?x=%E0%A4` | `?x=%EF%BF%BD` | A malformed escape is decoded and re-encoded as U+FFFD: the stored URL is corrupted. |
| `?campaign_id=123` | (removed) | On an ads dashboard that parameter *is* the page. |
| `#/settings/profile` | (removed) | Hash-routed apps name their pages in the fragment; every page collapses to the app's root. |
| `http://[::1]:8080/x` | `http://::1:8080/x` | Brackets dropped: not a valid URL. |
| `chrome://extensions` | accepted | Not a web page; nothing can fetch it. |
| `about:blank` | "Port could not be cast to integer" | Rejected, with an error about something else. |

Two entries are also simply wrong: `trkCampaign` is in the tracking list in mixed case and keys are lowercased before the lookup, so it never matches; and `HASHBANG_HOSTS` keeps `#!` fragments only for three hosts, although any site may route on them.

The benefit the aggressive rules were meant to buy is unmeasured.
The predecessor's 2,216 duplicate rows (audit, 2026-09-20) are exact-string repeats from an endpoint that inserted on every call.
Any normaliser at all, even none, removes those once the insert is an upsert.

The corpus is one save.
Every rule changed now is free; every rule changed later needs a rehash of existing rows, and spellings that an old rule discarded cannot be recovered.

## Options

### A. Keep the rules, fix the bugs

Fix IPv6, the mixed-case tracking entry and the error messages; keep stripping, sorting and re-encoding.

Lost because it keeps every wrong merge in the table above, in exchange for duplicates nobody has measured.

### B. No normalisation: the URL as saved is the identity

Lost because two things are worth merging and cost nothing: spellings RFC 3986 defines as the same resource (`HTTPS://Example.COM:443/`), and click trackers (`?utm_source=newsletter`), which are the commonest reason the same page arrives under two spellings.

### C. Aggressive identity, original stored

Keep today's rules for `url_hash`, but store the URL as first saved in `bookmark.url`.

Lost because it fixes the link and keeps the merge.
Two different pages still share one row, the second saver still gets the first saver's page, and which URL the row holds depends on who saved first.

### D. Merge only spellings of the same resource

The normaliser applies transformations that cannot change which resource a URL names, plus removal of a curated list of click trackers, and nothing else.
Its output is both the identity and the stored URL, as now.

This is the decision.

## Decision

**Only http and https are accepted.**
Anything else is a 422 that names the scheme.
The crawler can fetch nothing else, `chrome://` and `about:` are not pages, and a `file://` path means nothing on another machine.
A bare `example.com/x` still gets `https://`, as now.

**These transformations, and only these:**

- **Scheme and host are lowercased**, and a trailing dot on the host is dropped.
- **An internationalised host is converted to its ASCII (punycode) form**, which is what Chrome reports for a tab, so a typed `bücher.de` and a saved `xn--bcher-kva.de` are one host.
- **An IPv6 host keeps its brackets.**
- **The default port is dropped**; any other port is kept.
- **Userinfo is dropped.** Credentials are not identity and do not belong in the database; this is the one deliberate exception to "never change the resource", and it is unchanged.
- **An empty path becomes `/`.** RFC 3986 defines them as equivalent for http.
- **Percent-escapes are normalised as RFC 3986 section 6.2.2 allows:** hex digits uppercased, and escapes of unreserved characters (`%7E`) decoded (`~`).
  Nothing else is decoded, and a malformed escape is left exactly as it was.
- **Tracking parameters are removed by editing the query string in place.**
  The parameters that remain keep their order, their encoding, and the difference between `?edit` and `?edit=`.
  If none remain, the `?` goes too.
- **The fragment is dropped, unless it is a route.**
  A fragment starting with `/` or `!` is kept on every host, because hash-routed apps name their pages there.
  Every other fragment, including a text fragment (`#:~:text=`), is a position within the page and goes.

**Nothing else.**
The trailing slash stays, the query is not sorted, `http` and `https` stay distinct, and `www.` stays distinct.
Each of those merges spellings that usually name the same page, and "usually" is the failure this decision exists to remove.

**A parameter is on the tracking list only if it is a known click or campaign tracker whose value never selects content.**
The list keeps the prefixes `utm_`, `pk_`, `mc_`, `hsa_`, `vero_`, `_hs` and the names `fbclid`, `gclid`, `dclid`, `gbraid`, `wbraid`, `msclkid`, `twclid`, `igshid`, `yclid`, `mkt_tok`, `s_kwcid`.
It drops `campaign_id`, `cmpid`, `icid`, `scid`, `trk`, `trkCampaign`, `ref_src` and `ref_url`: generic names that some site somewhere uses to select what it shows.
Entries are stored lowercase and matched case-insensitively.

## Consequences

- Some pages will now be saved twice under two spellings: `/docs` and `/docs/`, or the same query in two orders.
  That is the accepted cost.
  A merge is recoverable: M6's sidebar can offer "these look like the same page" as a review queue, the same way the audit treats near-duplicate tags.
- **Existing rows need rehashing whenever the rules change**, and they will change again: the tracking list grows.
  A `make rehash-urls` command recomputes `url` and `url_hash` for every `bookmark` row, reports rows whose new key collides with another row's instead of merging them, and does nothing without `CONFIRM=yes`.
  It lives in the API package, beside the normaliser it runs, so no Alembic revision is involved: the schema does not change.
  It runs once for this decision, against the one real save.
- A spelling an old rule discarded stays discarded.
  With one row that is academic, which is why this is decided now.
- The URL tests change in both directions.
  The pinned cases for stripping and sorting flip, and every row of the table above becomes a guard that must stay distinct or must come out exactly as saved.
