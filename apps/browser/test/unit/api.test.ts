import { describe, expect, it } from 'vitest';

import { Api, ApiError, errorMessage, isOffline } from '../../src/main/api';

type Call = { url: string; init: RequestInit | undefined };

function fake(...responses: { status: number; body?: unknown }[]) {
  const calls: Call[] = [];
  const fetchImpl = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const next = responses.shift() ?? { status: 500 };
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), { status: next.status });
  };
  return { api: new Api({ baseUrl: 'http://api.test/', token: 't0ken' }, fetchImpl), calls };
}

const bookmark = { id: 1, url: 'https://a.test/', title: 'A', site: 'a.test', saved_from: 'smart-browser', created_at: null, tags: ['x'] };

describe('Api', () => {
  it('sends the token on every request but health', async () => {
    const { api, calls } = fake({ status: 200, body: { status: 'ok' } }, { status: 200, body: [] });
    await api.health();
    await api.tags();
    expect(new Headers(calls[0]!.init!.headers).get('authorization')).toBeNull();
    expect(new Headers(calls[1]!.init!.headers).get('authorization')).toBe('Bearer t0ken');
    expect(calls[1]!.url).toBe('http://api.test/api/v1/tags?min_count=1&limit=2000');
  });

  it('looks a page up, and a 404 means not saved rather than an error', async () => {
    const { api, calls } = fake({ status: 200, body: bookmark }, { status: 404, body: { detail: 'Not saved.' } });
    expect(await api.lookup('https://a.test/?q=1#x')).toEqual(bookmark);
    expect(calls[0]!.url).toBe('http://api.test/api/v1/bookmarks/lookup?url=https%3A%2F%2Fa.test%2F%3Fq%3D1%23x');
    expect(await api.lookup('https://b.test/')).toBeNull();
  });

  it('saves with the title seen and says it is the browser saving', async () => {
    const { api, calls } = fake({ status: 201, body: bookmark });
    await api.save({ url: 'https://a.test/', title: 'A', tags: ['x'] });
    expect(calls[0]!.init!.method).toBe('POST');
    expect(JSON.parse(String(calls[0]!.init!.body))).toEqual({
      url: 'https://a.test/',
      title: 'A',
      saved_from: 'smart-browser',
      tags: ['x'],
    });
  });

  it('encodes a tag with a slash when removing it', async () => {
    const { api, calls } = fake({ status: 200, body: bookmark });
    await api.removeTag(1, 'ci/cd');
    expect(calls[0]!.url).toBe('http://api.test/api/v1/bookmarks/1/tags/ci%2Fcd');
  });

  it('turns an unreachable API into a readable error', async () => {
    const api = new Api({ baseUrl: 'http://api.test', token: 't' }, async () => {
      throw new TypeError('fetch failed');
    });
    await expect(api.health()).rejects.toThrow('Cannot reach http://api.test: fetch failed');
  });

  it('raises the status and the server’s reason', async () => {
    const { api } = fake({ status: 403, body: { detail: 'Invalid token.' } });
    await expect(api.tags()).rejects.toEqual(new ApiError('Token rejected. Check Settings.', 403));
  });
});

describe('errorMessage', () => {
  it('shows the first validation error without FastAPI’s prefix', () => {
    const payload = { detail: [{ msg: "Value error, tag 'a b': tag names cannot contain commas" }] };
    expect(errorMessage(422, payload)).toBe("tag 'a b': tag names cannot contain commas");
  });

  it('explains a server with no tokens as refusing, not down', () => {
    expect(errorMessage(503, null)).toMatch(/no API tokens configured/);
  });

  it('falls back to the status when there is no reason', () => {
    expect(errorMessage(500, null)).toBe('Request failed (500).');
  });
});

describe('offline or refused (ADR 0017)', () => {
  const failure = async (response: { status: number; body?: unknown } | 'unreachable') => {
    const fetchImpl = async () => {
      if (response === 'unreachable') throw new TypeError('fetch failed');
      return new Response(response.body === undefined ? '<html>Bad gateway</html>' : JSON.stringify(response.body), {
        status: response.status,
      });
    };
    const api = new Api({ baseUrl: 'http://api.test', token: 't' }, fetchImpl);
    return api.save({ url: 'https://a.test/', title: null, tags: [] }).then(
      () => null,
      (error: unknown) => error,
    );
  };

  it('is offline when nothing that is the API answered', async () => {
    for (const response of ['unreachable', { status: 502 }, { status: 503 }, { status: 504 }] as const) {
      const error = await failure(response);
      expect(isOffline(error), JSON.stringify(response)).toBe(true);
      expect((error as ApiError).message).toMatch(/^Cannot reach http:\/\/api\.test/);
    }
  });

  it('is refused when the API itself answered no, its own 503 included', async () => {
    for (const status of [401, 403, 422, 500]) {
      expect(isOffline(await failure({ status, body: { detail: 'No.' } })), String(status)).toBe(false);
    }
    const noTokens = await failure({ status: 503, body: { detail: 'No API tokens configured; writes are disabled.' } });
    expect(isOffline(noTokens)).toBe(false);
    expect((noTokens as ApiError).message).toBe('The server has no API tokens configured, so it is refusing requests.');
  });
});
