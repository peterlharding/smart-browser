import { describe, expect, it } from 'vitest';

import { Lookups, pageKey } from '../../src/main/lookups';

const saved = { kind: 'saved' as const, tags: ['x'] };
const unsaved = { kind: 'unsaved' as const };

/** A clock the test moves, and an API whose answers the test releases. */
function setup() {
  let now = 1_000;
  const clock = { now: () => now, advance: (ms: number) => (now += ms) };
  const calls: string[] = [];
  const release: Array<() => void> = [];
  const ask = (url: string, answer: typeof saved | typeof unsaved = unsaved) => () => {
    calls.push(url);
    return new Promise<typeof answer>((resolve) => release.push(() => resolve(answer)));
  };
  return { lookups: new Lookups(clock.now, 60_000), clock, calls, release, ask };
}

describe('Lookups', () => {
  it('answers a page asked about in the last minute without asking again', async () => {
    const { lookups, calls, release, ask } = setup();
    const first = lookups.lookup('https://a.test/', ask('https://a.test/'));
    release.shift()!();
    expect(await first).toEqual(unsaved);

    expect(await lookups.lookup('https://a.test/', ask('https://a.test/'))).toEqual(unsaved);
    expect(calls).toEqual(['https://a.test/']);
  });

  it('shares a lookup already in flight, as a page loading in stages would repeat it', async () => {
    const { lookups, calls, release, ask } = setup();
    const answers = [1, 2, 3, 4].map(() => lookups.lookup('https://a.test/', ask('https://a.test/')));
    release.shift()!();
    expect(await Promise.all(answers)).toEqual([unsaved, unsaved, unsaved, unsaved]);
    expect(calls).toHaveLength(1);
  });

  it('asks again once the answer is a minute old', async () => {
    const { lookups, clock, calls, release, ask } = setup();
    const first = lookups.lookup('https://a.test/', ask('https://a.test/'));
    release.shift()!();
    await first;
    clock.advance(60_000);
    const again = lookups.lookup('https://a.test/', ask('https://a.test/'));
    release.shift()!();
    await again;
    expect(calls).toHaveLength(2);
  });

  it('keeps no failure, so the next lookup asks again', async () => {
    const { lookups } = setup();
    let asked = 0;
    const failing = () => {
      asked += 1;
      return Promise.reject(new Error('unreachable'));
    };
    await expect(lookups.lookup('https://a.test/', failing)).rejects.toThrow('unreachable');
    await expect(lookups.lookup('https://a.test/', failing)).rejects.toThrow('unreachable');
    expect(asked).toBe(2);
  });

  it('takes a save’s result as the answer', async () => {
    const { lookups, calls, ask } = setup();
    lookups.remember('https://a.test/', saved);
    expect(await lookups.lookup('https://a.test/', ask('https://a.test/'))).toEqual(saved);
    expect(calls).toEqual([]);
  });

  it('never lets a lookup that started before a save overwrite it', async () => {
    const { lookups, clock, release, ask } = setup();
    const stale = lookups.lookup('https://a.test/', ask('https://a.test/', unsaved));
    clock.advance(10);
    lookups.remember('https://a.test/', saved); // the save lands while the lookup is out
    release.shift()!();
    await stale;
    expect(await lookups.lookup('https://a.test/', ask('https://a.test/'))).toEqual(saved);
  });

  it('forgets a page on reload, and everything on new settings', async () => {
    const { lookups, calls, release, ask } = setup();
    lookups.remember('https://a.test/', saved);
    lookups.remember('https://b.test/', saved);

    lookups.forget('https://a.test/');
    const a = lookups.lookup('https://a.test/', ask('https://a.test/'));
    release.shift()!();
    await a;
    expect(await lookups.lookup('https://b.test/', ask('https://b.test/'))).toEqual(saved);
    expect(calls).toEqual(['https://a.test/']);

    lookups.forget();
    const b = lookups.lookup('https://b.test/', ask('https://b.test/'));
    release.shift()!();
    await b;
    expect(calls).toEqual(['https://a.test/', 'https://b.test/']);
  });

  it('does not keep an answer asked for before settings changed', async () => {
    const { lookups, calls, release, ask } = setup();
    const old = lookups.lookup('https://a.test/', ask('https://a.test/', saved)); // the old API
    lookups.forget();
    release.shift()!();
    await old;
    const fresh = lookups.lookup('https://a.test/', ask('https://a.test/'));
    release.shift()!();
    expect(await fresh).toEqual(unsaved);
    expect(calls).toHaveLength(2);
  });

  it('keeps a bounded number of pages, dropping the oldest', async () => {
    const { lookups, calls, ask } = setup();
    for (let i = 0; i <= 100; i += 1) lookups.remember(`https://p${i}.test/`, saved);
    void lookups.lookup('https://p0.test/', ask('https://p0.test/'));
    expect(await lookups.lookup('https://p100.test/', ask('https://p100.test/'))).toEqual(saved);
    expect(calls).toEqual(['https://p0.test/']);
  });
});

describe('pageKey', () => {
  it('drops a fragment that is a position within the page, as the API does', () => {
    expect(pageKey('https://a.test/p#top')).toBe('https://a.test/p');
    expect(pageKey('https://a.test/p#:~:text=hello')).toBe('https://a.test/p');
  });

  it('keeps a fragment that is a route, which the API keeps too', () => {
    expect(pageKey('https://app.test/#/settings')).toBe('https://app.test/#/settings');
    expect(pageKey('https://x.test/i#!/status/1')).toBe('https://x.test/i#!/status/1');
  });

  it('keeps the query, which names a different page', () => {
    expect(pageKey('https://a.test/p?step=1')).not.toBe(pageKey('https://a.test/p'));
  });
});

it('answers a page and the same page at an anchor from one lookup', async () => {
  const lookups = new Lookups();
  let asked = 0;
  const ask = async () => {
    asked += 1;
    return { kind: 'unsaved' as const };
  };
  await lookups.lookup('https://a.test/p', ask);
  await lookups.lookup('https://a.test/p#top', ask);
  expect(asked).toBe(1);
});

