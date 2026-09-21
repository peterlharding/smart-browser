/**
 * Where you have been, kept on this machine and nowhere else (ADR 0016): visits, the tabs
 * you closed, and which pages this browser knows you saved.
 *
 * SQLite through Node's built-in `node:sqlite`, which Electron bundles, so there is no
 * native module to rebuild. The clock is a parameter, so the tests move time instead of
 * waiting for it.
 */

import { DatabaseSync } from 'node:sqlite';

import type { ClearRange, HistoryEntry, HistoryQuery, HistoryResult } from '../shared/ipc';
import { hostOf, pageKey } from './urls';

/** As long as Chrome keeps it. */
export const KEEP_DAYS = 90;
/** Recently closed tabs kept, and so offered in the menu. */
export const CLOSED_TABS = 10;
const PAGE_SIZE = 100;
const MAX_PAGE_SIZE = 500;
const DAY_MS = 24 * 60 * 60 * 1000;

export interface ClosedTab {
  id: number;
  url: string;
  title: string;
  /** The page's favicon from history, if it is still there: not kept twice. */
  favicon: string | null;
  /** Where the tab stood in its window, so it reopens there. */
  index: number;
  /** Its back and forward history, as Electron's navigationHistory gives and takes it. */
  navigation: { entries: Array<{ url: string; title: string; pageState?: string }>; index: number };
}

export type NewClosedTab = Omit<ClosedTab, 'id' | 'favicon'>;

export interface RecentPage {
  url: string;
  title: string;
  favicon: string | null;
}

// Each step takes the database from the version before it to its own. PRAGMA user_version
// records how far a profile has come, so a step never runs twice.
const MIGRATIONS = [
  `
  CREATE TABLE page (
    id      INTEGER PRIMARY KEY,
    url     TEXT NOT NULL UNIQUE,
    host    TEXT NOT NULL,
    title   TEXT NOT NULL DEFAULT '',
    favicon TEXT
  );
  CREATE TABLE visit (
    id      INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES page (id) ON DELETE CASCADE,
    at      INTEGER NOT NULL,
    day     TEXT NOT NULL
  );
  CREATE INDEX visit_at ON visit (at);
  CREATE INDEX visit_page_day ON visit (page_id, day);

  CREATE VIRTUAL TABLE page_search USING fts5 (title, url, content = 'page', content_rowid = 'id');
  CREATE TRIGGER page_search_insert AFTER INSERT ON page BEGIN
    INSERT INTO page_search (rowid, title, url) VALUES (new.id, new.title, new.url);
  END;
  CREATE TRIGGER page_search_delete AFTER DELETE ON page BEGIN
    INSERT INTO page_search (page_search, rowid, title, url) VALUES ('delete', old.id, old.title, old.url);
  END;
  CREATE TRIGGER page_search_update AFTER UPDATE OF title, url ON page BEGIN
    INSERT INTO page_search (page_search, rowid, title, url) VALUES ('delete', old.id, old.title, old.url);
    INSERT INTO page_search (rowid, title, url) VALUES (new.id, new.title, new.url);
  END;

  CREATE TABLE closed_tab (
    id         INTEGER PRIMARY KEY,
    closed_at  INTEGER NOT NULL,
    url        TEXT NOT NULL,
    title      TEXT NOT NULL,
    position   INTEGER NOT NULL,
    navigation TEXT NOT NULL
  );

  CREATE TABLE saved (
    url  TEXT PRIMARY KEY,
    tags TEXT NOT NULL,
    at   INTEGER NOT NULL
  );
  `,
];

/** The local calendar day of *at*, as history groups visits: "2026-09-22". */
export function dayOf(at: number): string {
  const date = new Date(at);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * What the search box means: each word must start a word of the title or the address, in
 * any order, as Chrome's history search behaves. Quoted for FTS5, so nothing typed is
 * taken as query syntax. Null when nothing typed could match a word at all.
 */
export function searchQuery(text: string): string | null {
  const words = text
    .split(/\s+/)
    .filter((word) => /[\p{L}\p{N}]/u.test(word))
    .map((word) => `"${word.replace(/"/g, '""')}"*`);
  return words.length ? words.join(' ') : null;
}

export class History {
  private readonly db: DatabaseSync;
  private readonly listeners = new Set<() => void>();

  constructor(
    file: string,
    private readonly now: () => number = Date.now,
  ) {
    this.db = new DatabaseSync(file);
    this.db.exec('PRAGMA journal_mode = WAL');
    this.db.exec('PRAGMA foreign_keys = ON');
    // Deleted history is overwritten, not left in free pages for anyone to read back.
    this.db.exec('PRAGMA secure_delete = ON');
    this.migrate();
  }

  close(): void {
    this.db.close();
  }

  /** Called after anything changes, so the menu and open history pages can follow. */
  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  // --- visits ----------------------------------------------------------------------------

  /**
   * A page committed in a tab. Its title and favicon often arrive afterwards: see update().
   * A page is its address without a fragment that is only a place in it, so `#section` is
   * not a page of its own (see pageKey).
   */
  recordVisit(visited: string, title = ''): void {
    if (!this.db.isOpen) return; // late work, a favicon or a save, finishing as the app quits
    const url = pageKey(visited);
    const at = this.now();
    const page = this.db
      .prepare(
        `INSERT INTO page (url, host, title) VALUES (?, ?, ?)
         ON CONFLICT (url) DO UPDATE SET title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE title END
         RETURNING id`,
      )
      .get(url, hostOf(url), title) as { id: number };
    this.db.prepare('INSERT INTO visit (page_id, at, day) VALUES (?, ?, ?)').run(page.id, at, dayOf(at));
    this.changed();
  }

  /** The title or favicon a visited page set after it loaded. Pages not visited are ignored. */
  update(page: string, { title, favicon }: { title?: string; favicon?: string }): void {
    if (!this.db.isOpen) return;
    const url = pageKey(page);
    const result = this.db
      .prepare(
        `UPDATE page SET title = coalesce(?, title), favicon = coalesce(?, favicon)
         WHERE url = ? AND (title IS NOT coalesce(?, title) OR favicon IS NOT coalesce(?, favicon))`,
      )
      .run(title || null, favicon ?? null, url, title || null, favicon ?? null);
    if (result.changes) this.changed();
  }

  /**
   * Visits, newest first, one row per page per day, as Chrome lists them. *before* is the
   * `at` of the last row already shown, to continue from.
   */
  query({ text, host, day, before, limit }: HistoryQuery = {}): HistoryResult {
    const size = Math.min(Math.max(1, Math.floor(limit ?? PAGE_SIZE)), MAX_PAGE_SIZE);
    const match = text?.trim() ? searchQuery(text) : null;
    if (text?.trim() && !match) return { entries: [], more: false };
    const rows = this.db
      .prepare(
        `SELECT p.id AS pageId, v.day AS day, p.url AS url, p.title AS title, p.host AS host,
                p.favicon AS favicon, max(v.at) AS at
         FROM visit v JOIN page p ON p.id = v.page_id
         WHERE (:host IS NULL OR p.host = :host)
           AND (:day IS NULL OR v.day = :day)
           AND (:match IS NULL OR p.id IN (SELECT rowid FROM page_search WHERE page_search MATCH :match))
         GROUP BY p.id, v.day
         HAVING (:before IS NULL OR max(v.at) < :before)
         ORDER BY at DESC, p.id DESC
         LIMIT :size`,
      )
      .all({ host: host || null, day: day || null, match, before: before ?? null, size: size + 1 }) as unknown[];
    const entries = (rows as HistoryEntry[]).slice(0, size).map((row) => ({ ...row }));
    return { entries, more: rows.length > size };
  }

  /** The pages visited most recently, each once, for the History menu. */
  recent(limit: number): RecentPage[] {
    return this.db
      .prepare(
        `SELECT p.url AS url, p.title AS title, p.favicon AS favicon
         FROM visit v JOIN page p ON p.id = v.page_id
         GROUP BY p.id ORDER BY max(v.at) DESC, p.id DESC LIMIT ?`,
      )
      .all(limit)
      .map((row) => ({ ...(row as unknown as RecentPage) }));
  }

  /** The days before today with any visits, newest first, at most *count* days back. */
  earlierDays(count: number): string[] {
    const today = dayOf(this.now());
    const from = dayOf(this.now() - count * DAY_MS);
    return this.db
      .prepare('SELECT DISTINCT day FROM visit WHERE day < ? AND day >= ? ORDER BY day DESC')
      .all(today, from)
      .map((row) => (row as { day: string }).day);
  }

  /** Delete these rows of the history page: each is a page's visits on one day. */
  remove(items: Array<{ pageId: number; day: string }>): void {
    const remove = this.db.prepare('DELETE FROM visit WHERE page_id = ? AND day = ?');
    this.transaction(() => {
      for (const { pageId, day } of items) remove.run(pageId, day);
      this.dropUnvisitedPages();
    });
    this.changed();
  }

  /** Delete browsing history over *range*: visits, and tabs closed in it. */
  clear(range: ClearRange): void {
    const since = rangeStart(range, this.now());
    this.transaction(() => {
      this.db.prepare('DELETE FROM visit WHERE at >= ?').run(since);
      this.db.prepare('DELETE FROM closed_tab WHERE closed_at >= ?').run(since);
      this.dropUnvisitedPages();
    });
    this.changed();
  }

  /** Forget what is older than KEEP_DAYS, as Chrome does. Run at launch. */
  prune(): void {
    const cutoff = this.now() - KEEP_DAYS * DAY_MS;
    this.transaction(() => {
      this.db.prepare('DELETE FROM visit WHERE at < ?').run(cutoff);
      this.db.prepare('DELETE FROM closed_tab WHERE closed_at < ?').run(cutoff);
      this.dropUnvisitedPages();
    });
  }

  // --- recently closed tabs --------------------------------------------------------------

  pushClosed(tab: NewClosedTab): void {
    if (!this.db.isOpen) return;
    this.transaction(() => {
      this.db
        .prepare(
          'INSERT INTO closed_tab (closed_at, url, title, position, navigation) VALUES (?, ?, ?, ?, ?)',
        )
        .run(this.now(), tab.url, tab.title, tab.index, JSON.stringify(tab.navigation));
      this.db
        .prepare('DELETE FROM closed_tab WHERE id NOT IN (SELECT id FROM closed_tab ORDER BY id DESC LIMIT ?)')
        .run(CLOSED_TABS);
    });
    this.changed();
  }

  /** The tabs closed most recently, newest first. */
  closed(): ClosedTab[] {
    return this.db
      .prepare(
        `SELECT c.id, c.url, c.title, p.favicon, c.position, c.navigation
         FROM closed_tab c LEFT JOIN page p ON p.url = c.url ORDER BY c.id DESC`,
      )
      .all()
      .map((row) => {
        const r = row as { id: number; url: string; title: string; favicon: string | null; position: number; navigation: string };
        return {
          id: r.id,
          url: r.url,
          title: r.title,
          favicon: r.favicon,
          index: r.position,
          navigation: JSON.parse(r.navigation) as ClosedTab['navigation'],
        };
      });
  }

  /** Take a closed tab off the list to reopen it: the newest, or the one with *id*. */
  takeClosed(id?: number): ClosedTab | null {
    const tab = this.closed().find((t) => id === undefined || t.id === id) ?? null;
    if (tab) {
      this.db.prepare('DELETE FROM closed_tab WHERE id = ?').run(tab.id);
      this.changed();
    }
    return tab;
  }

  // --- pages this browser saved ----------------------------------------------------------

  /** The tags a page was saved with, if this browser saved it or saw it saved; else null. */
  savedTags(url: string): string[] | null {
    const row = this.db.prepare('SELECT tags FROM saved WHERE url = ?').get(pageKey(url)) as { tags: string } | undefined;
    return row ? (JSON.parse(row.tags) as string[]) : null;
  }

  markSaved(url: string, tags: string[]): void {
    if (!this.db.isOpen) return;
    this.db
      .prepare('INSERT INTO saved (url, tags, at) VALUES (?, ?, ?) ON CONFLICT (url) DO UPDATE SET tags = excluded.tags, at = excluded.at')
      .run(pageKey(url), JSON.stringify(tags), this.now());
    this.changed();
  }

  /** The API says the page is not saved, whatever was known before: removed elsewhere, say. */
  markUnsaved(url: string): void {
    if (!this.db.isOpen) return;
    const result = this.db.prepare('DELETE FROM saved WHERE url = ?').run(pageKey(url));
    if (result.changes) this.changed();
  }

  // --- internals -------------------------------------------------------------------------

  private migrate(): void {
    const { user_version: version } = this.db.prepare('PRAGMA user_version').get() as { user_version: number };
    if (version > MIGRATIONS.length) {
      throw new Error(`history.db is at version ${version}, newer than this browser knows (${MIGRATIONS.length}).`);
    }
    MIGRATIONS.slice(version).forEach((step, i) => {
      this.transaction(() => {
        this.db.exec(step);
        this.db.exec(`PRAGMA user_version = ${version + i + 1}`);
      });
    });
  }

  private dropUnvisitedPages(): void {
    this.db.exec('DELETE FROM page WHERE NOT EXISTS (SELECT 1 FROM visit WHERE visit.page_id = page.id)');
  }

  private transaction(work: () => void): void {
    this.db.exec('BEGIN');
    try {
      work();
      this.db.exec('COMMIT');
    } catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }

  private changed(): void {
    for (const listener of this.listeners) listener();
  }
}

/** When "the last hour" and the rest begin; "all time" is the beginning. */
export function rangeStart(range: ClearRange, now: number): number {
  const hours = { hour: 1, day: 24, week: 24 * 7, month: 24 * 28, all: 0 }[range];
  return hours ? now - hours * 60 * 60 * 1000 : 0;
}
