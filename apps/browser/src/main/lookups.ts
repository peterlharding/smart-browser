/**
 * The answers to "is this page saved?", kept per page for a minute.
 *
 * The toolbar's indicator asks on every navigation event and every tab switch, and a page
 * that loads in stages (redirects, pushState, hash changes) raises several in a second:
 * the API log showed the same page looked up four times running. This answers repeats
 * from what it already knows, and shares a lookup already in flight.
 *
 * Only real answers are kept, saved or not saved; a failure is not, so it is retried.
 * A save or a tag removal writes its result here directly, a reload forgets the page, and
 * new settings forget everything, since they may name a different API.
 */

import type { SavedState } from '../shared/ipc';

type Answer = Extract<SavedState, { kind: 'saved' } | { kind: 'unsaved' }>;

const TTL_MS = 60_000;
const MAX_PAGES = 100;

/**
 * A page as the API tells pages apart: the fragment is a position within the page, not a
 * different one, unless it is a route starting `/` or `!` (ADR 0011). So `#top` after a
 * page loads is the same bookmark, answered from what is already known.
 */
export function pageKey(url: string): string {
  try {
    const parsed = new URL(url);
    if (parsed.hash && !/^#[/!]/.test(parsed.hash)) parsed.hash = '';
    return parsed.href;
  } catch {
    return url;
  }
}

export class Lookups {
  private readonly answers = new Map<string, { answer: Answer; at: number }>();
  private readonly pending = new Map<string, Promise<Answer>>();
  // Moved on by forget(), so an answer asked for before it -- from the API the old
  // settings named, or about the page before its reload -- is not kept after it.
  private generation = 0;

  constructor(
    private readonly now: () => number = Date.now,
    private readonly ttlMs = TTL_MS,
  ) {}

  /** The answer for *url*: known and fresh, already being asked, or asked now. */
  async lookup(page: string, ask: () => Promise<Answer>): Promise<Answer> {
    const url = pageKey(page);
    const known = this.answers.get(url);
    if (known && this.now() - known.at < this.ttlMs) return known.answer;

    const inFlight = this.pending.get(url);
    if (inFlight) return inFlight;

    const generation = this.generation;
    const asked = this.now();
    const asking = ask()
      .then((answer) => {
        // Kept unless something newer is known: a save that finished while this was in
        // flight is a later answer than this one, and must not be overwritten by it.
        const newer = this.answers.get(url);
        if (generation === this.generation && !(newer && newer.at >= asked)) {
          this.remember(url, answer);
        }
        return answer;
      })
      .finally(() => {
        if (this.pending.get(url) === asking) this.pending.delete(url);
      });
    this.pending.set(url, asking);
    return asking;
  }

  /** What a save or a tag removal just established. */
  remember(page: string, answer: Answer): void {
    const url = pageKey(page);
    this.answers.delete(url); // re-inserted last, so the oldest page is first to go
    this.answers.set(url, { answer, at: this.now() });
    if (this.answers.size > MAX_PAGES) {
      const oldest = this.answers.keys().next().value;
      if (oldest !== undefined) this.answers.delete(oldest);
    }
  }

  /** Forget one page (a reload), or everything (new settings). */
  forget(page?: string): void {
    this.generation += 1;
    if (page === undefined) {
      this.answers.clear();
      this.pending.clear();
    } else {
      this.answers.delete(pageKey(page));
      this.pending.delete(pageKey(page));
    }
  }
}
