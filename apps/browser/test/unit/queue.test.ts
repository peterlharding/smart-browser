import { afterEach, describe, expect, it } from 'vitest';

import { Api, ApiError } from '../../src/main/api';
import { Connection } from '../../src/main/connection';
import { History } from '../../src/main/history';
import { RETRY_MINUTES, SaveQueue, type Timers } from '../../src/main/queue';

const open: History[] = [];
afterEach(() => {
  for (const history of open.splice(0)) history.close();
});

/** Timers the test fires by hand, and an API whose answers the test decides. */
function setup() {
  const history = new History(':memory:');
  open.push(history);
  const scheduled: Array<{ ms: number; fire: () => void; cleared: boolean }> = [];
  const timers: Timers = {
    set: (callback, ms) => {
      // A timer that has fired is spent, as a real one is.
      const timer = { ms, fire: () => ((timer.cleared = true), callback()), cleared: false };
      scheduled.push(timer);
      return timer;
    },
    clear: (handle) => {
      (handle as { cleared: boolean }).cleared = true;
    },
  };
  const sent: string[] = [];
  let answer: (url: string, tags: string[]) => Promise<unknown> = async (url, tags) => ({ url, tags });
  const api = {
    save: async ({ url, tags }: { url: string; tags: string[] }) => {
      sent.push(url);
      return answer(url, tags);
    },
  } as unknown as Api;
  let connected: Api | string | null = api;
  let connects = 0;
  const connection = {
    connect: async () => {
      connects += 1;
      return connected;
    },
  };
  const queue = new SaveQueue(history, connection, timers);
  return {
    history,
    queue,
    sent,
    connects: () => connects,
    answer: (fn: typeof answer) => (answer = fn),
    connect: (value: Api | string | null) => (connected = value),
    pending: () => scheduled.filter((t) => !t.cleared),
  };
}

const page = (n: number, tags: string[] = []) => ({ url: `https://p${n}.test/`, title: `P${n}`, tags });
const away = () => Promise.reject(new ApiError('Cannot reach http://api.test: fetch failed', 0, true));

describe('SaveQueue', () => {
  it('counts the attempt that found the API away as the first', () => {
    const { history, queue } = setup();
    queue.add(page(1), { failed: 'Cannot reach http://api.test: fetch failed' });
    expect(history.pendingFor('https://p1.test/')).toMatchObject({ attempts: 1, lastError: 'Cannot reach http://api.test: fetch failed' });
  });

  it('asks nothing while nothing waits', async () => {
    const { queue, connects, pending } = setup();
    expect(await queue.flush()).toBe('nothing');
    queue.start();
    expect(connects()).toBe(0);
    expect(pending()).toEqual([]);
  });

  it('delivers the oldest first, and marks each page saved with the tags the API kept', async () => {
    const { history, queue, sent } = setup();
    queue.add(page(1, ['x']));
    queue.add(page(2));
    expect(await queue.flush()).toBe('delivered');
    expect(sent).toEqual(['https://p1.test/', 'https://p2.test/']);
    expect(history.pendingSaves()).toEqual([]);
    expect(history.savedTags('https://p1.test/')).toEqual(['x']);
  });

  it('stops at the first sign the API is still away, and tries again later', async () => {
    const { history, queue, sent, answer, pending } = setup();
    queue.add(page(1));
    queue.add(page(2));
    answer(away);
    expect(await queue.flush()).toBe('offline');
    expect(sent).toEqual(['https://p1.test/']); // not p2: the API is away for it too
    expect(history.pendingFor('https://p1.test/')).toMatchObject({ attempts: 1, lastError: expect.stringMatching(/^Cannot reach/) });
    expect(pending()).toHaveLength(1);
  });

  it('moves past a save the API refuses, which then waits for you, not for the API', async () => {
    const { history, queue, sent, answer } = setup();
    queue.add(page(1, ['bad']));
    queue.add(page(2));
    answer(async (url, tags) => {
      if (url.includes('p1')) throw new ApiError('Tag names cannot contain a comma.', 422);
      return { url, tags };
    });
    expect(await queue.flush()).toBe('delivered');
    expect(sent).toEqual(['https://p1.test/', 'https://p2.test/']);
    expect(history.pendingFor('https://p1.test/')).toMatchObject({ refused: true, lastError: 'Tag names cannot contain a comma.' });
    expect(await queue.flush()).toBe('nothing'); // refused is not retried by itself
    expect(sent).toHaveLength(2);

    answer(async (url, tags) => ({ url, tags }));
    expect(await queue.retry()).toBe('delivered');
    expect(history.pendingSaves()).toEqual([]);
  });

  it('delivers tags queued while a delivery was on its way, in the same flush', async () => {
    const { history, queue, sent, answer } = setup();
    queue.add(page(1, ['x']));
    answer(async (url, tags) => {
      if (sent.length === 1) history.queueSave(page(1, ['y']));
      return { url, tags };
    });
    expect(await queue.flush()).toBe('delivered');
    expect(sent).toEqual(['https://p1.test/', 'https://p1.test/']);
    expect(history.savedTags('https://p1.test/')).toEqual(['x', 'y']);
  });

  it('joins a flush already running rather than delivering twice at once', async () => {
    const { queue, sent } = setup();
    queue.add(page(1));
    await Promise.all([queue.flush(), queue.flush(), queue.flush()]);
    expect(sent).toEqual(['https://p1.test/']);
  });

  it('waits longer each time the API is still away, then every ten minutes', async () => {
    const { queue, answer, pending } = setup();
    answer(away);
    queue.add(page(1));
    const waits: number[] = [pending()[0]!.ms];
    for (let i = 0; i < 5; i += 1) {
      const timer = pending()[0]!;
      timer.fire();
      await queue.flush();
      waits.push(pending()[0]!.ms);
    }
    expect(waits.map((ms) => ms / 60_000)).toEqual([...RETRY_MINUTES, 10, 10].slice(0, 6));
  });

  it('stops trying once nothing waits, and starts again from a minute', async () => {
    const { queue, answer, pending } = setup();
    answer(away);
    queue.add(page(1));
    await queue.flush();
    answer(async (url, tags) => ({ url, tags }));
    await queue.flush();
    expect(pending()).toEqual([]);
    queue.add(page(2));
    expect(pending()[0]!.ms).toBe(60_000);
  });

  it('delivers nothing while there is no API, or one speaking another contract', async () => {
    const { queue, sent, connect } = setup();
    queue.add(page(1));
    connect('The API speaks contract 2 and this browser speaks 1, so saving is off.');
    expect(await queue.flush()).toBe('blocked');
    connect(null);
    expect(await queue.flush()).toBe('blocked');
    expect(sent).toEqual([]);
  });

  it('drops a save, and with nothing left, stops the schedule', () => {
    const { history, queue, pending } = setup();
    queue.add(page(1));
    queue.drop(history.pendingSaves()[0]!.id);
    expect(history.pendingSaves()).toEqual([]);
    expect(pending()).toEqual([]);
  });

  it('delivers at launch what waited while the browser was closed', async () => {
    const { history, queue, sent } = setup();
    history.queueSave(page(1));
    queue.start();
    await queue.flush();
    expect(sent).toEqual(['https://p1.test/']);
  });
});

describe('Connection', () => {
  const settings = { apiUrl: 'http://api.test', token: () => 't' };
  const answering = (contract: number) => {
    let asked = 0;
    const fetchImpl = async () => {
      asked += 1;
      return new Response(JSON.stringify({ status: 'ok', contract, version: '0.5.0' }), { status: 200 });
    };
    return { fetchImpl, asked: () => asked };
  };

  it('asks the contract once, shared by callers asking together', async () => {
    const { fetchImpl, asked } = answering(1);
    const connection = new Connection(settings, fetchImpl);
    const [a, b] = await Promise.all([connection.connect(), connection.connect()]);
    expect(a).toBeInstanceOf(Api);
    expect(b).toBeInstanceOf(Api);
    await connection.connect();
    expect(asked()).toBe(1);
  });

  it('says why saving is off for another contract, until settings change', async () => {
    const { fetchImpl, asked } = answering(2);
    const connection = new Connection(settings, fetchImpl);
    expect(await connection.connect()).toMatch(/speaks contract 2/);
    expect(connection.problem()).toMatch(/speaks contract 2/);
    connection.reset();
    expect(connection.problem()).toBeNull();
    await connection.connect();
    expect(asked()).toBe(2);
  });

  it('is nothing without an address and a token, and asks nothing', async () => {
    const { fetchImpl, asked } = answering(1);
    expect(await new Connection({ apiUrl: '', token: () => 't' }, fetchImpl).connect()).toBeNull();
    expect(await new Connection({ apiUrl: 'http://api.test', token: () => null }, fetchImpl).connect()).toBeNull();
    expect(asked()).toBe(0);
  });
});
