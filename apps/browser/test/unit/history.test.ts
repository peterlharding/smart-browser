import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

import { afterEach, describe, expect, it } from 'vitest';

import { CLOSED_TABS, History, dayOf, rangeStart, searchQuery } from '../../src/main/history';

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
// Noon, local time, so a few hours either way stays on the same day.
const NOON = new Date(2026, 8, 22, 12, 0).getTime();

const open: History[] = [];

/** A history in memory, and a clock the test moves. */
function setup(file = ':memory:') {
  let now = NOON;
  const history = new History(file, () => now);
  open.push(history);
  return {
    history,
    at: (time: number) => (now = time),
    advance: (ms: number) => (now += ms),
  };
}

afterEach(() => {
  for (const history of open.splice(0)) {
    try {
      history.close();
    } catch {
      // already closed by the test
    }
  }
});

const urls = (history: History, query = {}) => history.query(query).entries.map((e) => e.url);

describe('visits', () => {
  it('lists one row per page per day, newest first, at its latest visit', () => {
    const { history, advance } = setup();
    history.recordVisit('https://a.test/', 'A');
    advance(60_000);
    history.recordVisit('https://b.test/', 'B');
    advance(60_000);
    history.recordVisit('https://a.test/', 'A');

    const { entries, more } = history.query();
    expect(entries.map((e) => [e.url, e.title, e.at])).toEqual([
      ['https://a.test/', 'A', NOON + 120_000],
      ['https://b.test/', 'B', NOON + 60_000],
    ]);
    expect(entries[0]).toMatchObject({ host: 'a.test', day: '2026-09-22', favicon: null });
    expect(more).toBe(false);
  });

  it('lists a page again on each day it was visited', () => {
    const { history, advance } = setup();
    history.recordVisit('https://a.test/', 'A');
    advance(DAY);
    history.recordVisit('https://a.test/', 'A');
    expect(history.query().entries.map((e) => e.day)).toEqual(['2026-09-23', '2026-09-22']);
  });

  it('keeps the title and favicon a page sets after it loads', () => {
    const { history } = setup();
    history.recordVisit('https://a.test/');
    history.update('https://a.test/', { title: 'Later title', favicon: 'data:image/png;base64,AAAA' });
    expect(history.query().entries[0]).toMatchObject({ title: 'Later title', favicon: 'data:image/png;base64,AAAA' });
  });

  it('does not forget a title when a visit arrives without one', () => {
    const { history } = setup();
    history.recordVisit('https://a.test/', 'A');
    history.recordVisit('https://a.test/', ''); // back to a cached page: no title event
    expect(history.query().entries[0]!.title).toBe('A');
  });

  it('ignores updates for pages never visited', () => {
    const { history } = setup();
    history.update('https://never.test/', { title: 'X' });
    expect(history.query().entries).toEqual([]);
  });

  it('continues a long list from the last row shown, without repeats or gaps', () => {
    const { history, advance } = setup();
    for (let i = 0; i < 7; i += 1) {
      history.recordVisit(`https://p${i}.test/`, `P${i}`);
      advance(1_000);
    }
    const first = history.query({ limit: 3 });
    expect(first.more).toBe(true);
    const second = history.query({ limit: 3, before: first.entries.at(-1)!.at });
    const third = history.query({ limit: 3, before: second.entries.at(-1)!.at });
    expect(third.more).toBe(false);
    expect([...first.entries, ...second.entries, ...third.entries].map((e) => e.title)).toEqual([
      'P6', 'P5', 'P4', 'P3', 'P2', 'P1', 'P0',
    ]);
  });

  it('narrows to a site, or a day', () => {
    const { history, advance } = setup();
    history.recordVisit('https://a.test/one', 'One');
    history.recordVisit('https://b.test/', 'B');
    advance(DAY);
    history.recordVisit('https://a.test/two', 'Two');
    expect(urls(history, { host: 'a.test' })).toEqual(['https://a.test/two', 'https://a.test/one']);
    expect(urls(history, { day: '2026-09-22' })).toEqual(['https://b.test/', 'https://a.test/one']);
  });
});

describe('search', () => {
  function searchable() {
    const { history, advance } = setup();
    history.recordVisit('https://blog.example/postgres-tuning', 'Tuning Postgres work_mem');
    advance(1_000);
    history.recordVisit('https://news.test/', 'Today in Rust');
    advance(1_000);
    history.recordVisit('http://127.0.0.1:8000/api/v1/docs', 'API docs');
    return history;
  }

  it('matches words that start words of the title or the address, in any order', () => {
    const history = searchable();
    expect(urls(history, { text: 'postgres' })).toEqual(['https://blog.example/postgres-tuning']);
    expect(urls(history, { text: 'tun pos' })).toEqual(['https://blog.example/postgres-tuning']);
    expect(urls(history, { text: 'example' })).toEqual(['https://blog.example/postgres-tuning']);
    expect(urls(history, { text: 'RUST' })).toEqual(['https://news.test/']);
    expect(urls(history, { text: '127.0.0.1' })).toEqual(['http://127.0.0.1:8000/api/v1/docs']);
  });

  it('needs every word to match', () => {
    expect(urls(searchable(), { text: 'postgres rust' })).toEqual([]);
  });

  it('takes nothing typed as query syntax', () => {
    const history = searchable();
    for (const text of ['"', 'postgres OR rust', 'NEAR(a b)', 'title:rust', '* ^', '"unclosed']) {
      expect(() => history.query({ text })).not.toThrow();
    }
    expect(urls(history, { text: 'postgres OR rust' })).toEqual([]);
    expect(urls(history, { text: '* ^' })).toEqual([]);
  });

  it('finds a title set after the visit, and forgets a deleted page', () => {
    const { history } = setup();
    history.recordVisit('https://a.test/');
    history.update('https://a.test/', { title: 'Kittens' });
    expect(urls(history, { text: 'kitten' })).toEqual(['https://a.test/']);
    history.remove([{ pageId: history.query().entries[0]!.pageId, day: '2026-09-22' }]);
    expect(urls(history, { text: 'kitten' })).toEqual([]);
  });

  it('quotes each word for FTS5', () => {
    expect(searchQuery('work "mem')).toBe('"work"* """mem"*');
    expect(searchQuery(' - ')).toBeNull();
  });
});

describe('deleting', () => {
  it('deletes a row: that page on that day, not on others', () => {
    const { history, advance } = setup();
    history.recordVisit('https://a.test/', 'A');
    advance(DAY);
    history.recordVisit('https://a.test/', 'A');
    const today = history.query().entries[0]!;
    history.remove([{ pageId: today.pageId, day: today.day }]);
    expect(history.query().entries.map((e) => e.day)).toEqual(['2026-09-22']);
  });

  it('clears the range asked for: visits and the tabs closed in it', () => {
    const { history, advance } = setup();
    history.recordVisit('https://old.test/', 'Old');
    history.pushClosed({ url: 'https://old.test/', title: 'Old', index: 0, navigation: { entries: [], index: 0 } });
    advance(2 * HOUR);
    history.recordVisit('https://new.test/', 'New');
    history.pushClosed({ url: 'https://new.test/', title: 'New', index: 0, navigation: { entries: [], index: 0 } });

    history.clear('hour');
    expect(urls(history)).toEqual(['https://old.test/']);
    expect(history.closed().map((t) => t.url)).toEqual(['https://old.test/']);

    history.clear('all');
    expect(urls(history)).toEqual([]);
    expect(history.closed()).toEqual([]);
  });

  it('keeps 90 days, as Chrome does', () => {
    const { history, advance } = setup();
    history.recordVisit('https://ancient.test/', 'Ancient');
    advance(89 * DAY);
    history.recordVisit('https://recent.test/', 'Recent');
    history.prune();
    expect(urls(history)).toEqual(['https://recent.test/', 'https://ancient.test/']);
    advance(2 * DAY);
    history.prune();
    expect(urls(history)).toEqual(['https://recent.test/']);
  });

  it('knows where each range starts', () => {
    expect(rangeStart('hour', NOON)).toBe(NOON - HOUR);
    expect(rangeStart('month', NOON)).toBe(NOON - 28 * DAY);
    expect(rangeStart('all', NOON)).toBe(0);
  });
});

describe('the History menu', () => {
  it('lists recent pages once each, newest first', () => {
    const { history, advance } = setup();
    history.recordVisit('https://a.test/', 'A');
    advance(DAY);
    history.recordVisit('https://b.test/', 'B');
    advance(1_000);
    history.recordVisit('https://a.test/', 'A');
    expect(history.recent(10).map((p) => p.title)).toEqual(['A', 'B']);
    expect(history.recent(1).map((p) => p.title)).toEqual(['A']);
  });

  it('names the days before today that have visits, as far back as asked', () => {
    const { history, at } = setup();
    for (const daysAgo of [10, 6, 2, 1, 0]) {
      at(NOON - daysAgo * DAY);
      history.recordVisit(`https://d${daysAgo}.test/`, `D${daysAgo}`);
    }
    at(NOON);
    expect(history.earlierDays(7)).toEqual(['2026-09-21', '2026-09-20', '2026-09-16']);
  });
});

describe('recently closed tabs', () => {
  const tab = (n: number) => ({
    url: `https://t${n}.test/`,
    title: `T${n}`,
    index: n,
    navigation: { entries: [{ url: `https://t${n}.test/`, title: `T${n}` }], index: 0 },
  });

  it('keeps the last ten, newest first, with their history', () => {
    const { history } = setup();
    for (let n = 0; n < CLOSED_TABS + 2; n += 1) history.pushClosed(tab(n));
    const closed = history.closed();
    expect(closed).toHaveLength(CLOSED_TABS);
    expect(closed[0]).toMatchObject({ title: 'T11', index: 11, navigation: tab(11).navigation });
    expect(closed.at(-1)!.title).toBe('T2');
  });

  it('takes the newest, or the one asked for, off the list', () => {
    const { history } = setup();
    for (const n of [1, 2, 3]) history.pushClosed(tab(n));
    expect(history.takeClosed()!.title).toBe('T3');
    const t1 = history.closed().find((t) => t.title === 'T1')!;
    expect(history.takeClosed(t1.id)!.title).toBe('T1');
    expect(history.closed().map((t) => t.title)).toEqual(['T2']);
    expect(history.takeClosed(999)).toBeNull();
  });

  it('shows the favicon history keeps for the page', () => {
    const { history } = setup();
    history.recordVisit('https://t1.test/', 'T1');
    history.update('https://t1.test/', { favicon: 'data:image/png;base64,AAAA' });
    history.pushClosed(tab(1));
    expect(history.closed()[0]!.favicon).toBe('data:image/png;base64,AAAA');
  });
});

describe('pages this browser saved', () => {
  it('remembers the tags, for the page and not its fragment', () => {
    const { history } = setup();
    expect(history.savedTags('https://a.test/p')).toBeNull();
    history.markSaved('https://a.test/p#top', ['postgres']);
    expect(history.savedTags('https://a.test/p')).toEqual(['postgres']);
    history.markSaved('https://a.test/p', []);
    expect(history.savedTags('https://a.test/p#later')).toEqual([]);
    history.markUnsaved('https://a.test/p');
    expect(history.savedTags('https://a.test/p')).toBeNull();
  });

  it('survives deleting browsing history: it records what you kept, not where you went', () => {
    const { history } = setup();
    history.markSaved('https://a.test/', ['x']);
    history.clear('all');
    expect(history.savedTags('https://a.test/')).toEqual(['x']);
  });
});

describe('the database', () => {
  let dir: string | undefined;
  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
    dir = undefined;
  });

  it('tells listeners what changed, so the menu and pages follow', () => {
    const { history } = setup();
    let changes = 0;
    const stop = history.onChange(() => (changes += 1));
    history.recordVisit('https://a.test/', 'A');
    history.update('https://a.test/', { title: 'A' }); // no change, no call
    history.markSaved('https://a.test/', []);
    stop();
    history.recordVisit('https://b.test/', 'B');
    expect(changes).toBe(2);
  });

  it('keeps history in its file across launches', () => {
    dir = mkdtempSync(join(tmpdir(), 'history-'));
    const file = join(dir, 'history.db');
    const first = setup(file).history;
    first.recordVisit('https://a.test/', 'A');
    first.close();
    expect(urls(setup(file).history)).toEqual(['https://a.test/']);
  });

  it('refuses a database from a newer browser rather than guess at it', () => {
    dir = mkdtempSync(join(tmpdir(), 'history-'));
    const file = join(dir, 'history.db');
    const db = new DatabaseSync(file);
    db.exec('PRAGMA user_version = 99');
    db.close();
    expect(() => new History(file)).toThrow(/version 99, newer than this browser knows/);
  });

  it('ignores what finishes after it is closed, as the app quits', () => {
    const { history } = setup();
    history.close();
    expect(() => history.recordVisit('https://a.test/', 'A')).not.toThrow();
    expect(() => history.update('https://a.test/', { favicon: 'x' })).not.toThrow();
    expect(() => history.markSaved('https://a.test/', [])).not.toThrow();
  });

  it('dates visits by the local day', () => {
    expect(dayOf(new Date(2026, 0, 5, 0, 30).getTime())).toBe('2026-01-05');
    expect(dayOf(new Date(2026, 0, 5, 23, 59).getTime())).toBe('2026-01-05');
  });
});
