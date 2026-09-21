import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { ApiError, BookmarksApi, NotConfigured, errorMessage } from '../src/lib/api.js';

/** A fetch stand-in that records calls and replays queued responses. */
function stubFetch(responses) {
  const calls = [];
  const queue = [...responses];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, ...options });
    const next = queue.shift();
    if (next instanceof Error) throw next;
    const { status = 200, body = null } = next ?? {};
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => {
        if (body === null) throw new Error('no body');
        return body;
      },
    };
  };
  return { fetchImpl, calls };
}

const api = (responses, settings = {}) => {
  const { fetchImpl, calls } = stubFetch(responses);
  return {
    client: new BookmarksApi({
      baseUrl: 'https://example.test',
      token: 'secret',
      fetchImpl,
      ...settings,
    }),
    calls,
  };
};

describe('configuration', () => {
  it('is not configured without a token', () => {
    const { client } = api([], { token: '' });
    assert.equal(client.configured, false);
  });

  it('calls the global fetch on the global, not on itself', async () => {
    // Chrome's fetch throws "Illegal invocation" when it is called on anything but the
    // window, so holding `globalThis.fetch` in a field and calling `this.fetch(...)`
    // fails on every request -- while passing here, because Node's fetch does not care.
    // This stand-in is deliberately as strict as the browser, so the suite can see it.
    const real = globalThis.fetch;
    let receiver = 'never called';
    globalThis.fetch = function strict() {
      receiver = this;
      if (this !== globalThis) throw new TypeError("Illegal invocation");
      return { ok: true, status: 200, json: async () => ({ status: 'ok' }) };
    };
    try {
      const client = new BookmarksApi({ baseUrl: 'https://example.test', token: 't' });
      await client.health();
    } finally {
      globalThis.fetch = real;
    }
    assert.equal(receiver, globalThis, 'fetch must be invoked on the global object');
  });

  it('strips trailing slashes so the path is not doubled', () => {
    const { client } = api([], { baseUrl: 'https://example.test///' });
    assert.equal(client.baseUrl, 'https://example.test');
  });

  it('refuses a write with no token rather than sending an unauthenticated one', async () => {
    const { client, calls } = api([{ status: 201, body: {} }], { token: '' });
    await assert.rejects(() => client.save({ url: 'https://x.test/' }), NotConfigured);
    assert.equal(calls.length, 0, 'must not hit the network');
  });

  it('refuses a read with no token: bookmarks belong to a user', async () => {
    const { client, calls } = api([{ status: 200, body: [] }], { token: '' });
    await assert.rejects(() => client.tags(), NotConfigured);
    assert.equal(calls.length, 0);
  });

  it('still allows health with no token, so the options page can test a connection', async () => {
    const { client } = api([{ status: 200, body: { status: 'ok' } }], { token: '' });
    assert.equal((await client.health()).status, 'ok');
  });
});

describe('lookup', () => {
  it('returns null for an unsaved page instead of throwing', async () => {
    const { client } = api([{ status: 404, body: { detail: 'Not saved.' } }]);
    assert.equal(await client.lookup('https://x.test/'), null);
  });

  it('returns the bookmark with its tags when saved', async () => {
    const { client } = api([{ status: 200, body: { id: 7, tags: ['python'] } }]);
    assert.deepEqual(await client.lookup('https://x.test/'), { id: 7, tags: ['python'] });
  });

  it('uses GET, so opening a popup cannot create a bookmark', async () => {
    const { client, calls } = api([{ status: 404, body: {} }]);
    await client.lookup('https://x.test/');
    assert.equal(calls[0].method, 'GET');
  });

  it('sends the token, because the answer is per-user', async () => {
    const { client, calls } = api([{ status: 404, body: {} }]);
    await client.lookup('https://x.test/');
    assert.equal(calls[0].headers.Authorization, 'Bearer secret');
  });

  it('encodes the url, so query strings and fragments survive', async () => {
    const { client, calls } = api([{ status: 404, body: {} }]);
    await client.lookup('https://x.test/a?b=1&c=2#d');
    assert.ok(calls[0].url.includes(encodeURIComponent('https://x.test/a?b=1&c=2#d')));
  });

  it('propagates errors that are not 404', async () => {
    const { client } = api([{ status: 500, body: null }]);
    await assert.rejects(() => client.lookup('https://x.test/'), ApiError);
  });
});

describe('save', () => {
  it('sends a bearer token and the tags', async () => {
    const { client, calls } = api([{ status: 201, body: { id: 1, tags: ['python'] } }]);
    await client.save({ url: 'https://x.test/', title: 'T', tags: ['python'] });

    assert.equal(calls[0].method, 'POST');
    assert.equal(calls[0].headers.Authorization, 'Bearer secret');
    assert.deepEqual(JSON.parse(calls[0].body), {
      url: 'https://x.test/',
      title: 'T',
      saved_from: 'chrome-extension',
      tags: ['python'],
    });
  });

  it('identifies itself in saved_from rather than posting an IP address', async () => {
    const { client, calls } = api([{ status: 201, body: {} }]);
    await client.save({ url: 'https://x.test/' });
    assert.equal(JSON.parse(calls[0].body).saved_from, 'chrome-extension');
  });
});

describe('save is the only write path', () => {
  it('is one POST whether or not the page already exists', async () => {
    for (const status of [200, 201]) {
      const { client, calls } = api([{ status, body: { id: 1, tags: ['python'] } }]);
      await client.save({ url: 'https://x.test/', tags: ['python'] });

      assert.equal(calls.length, 1, 'the client must not branch into a second request');
      assert.equal(calls[0].method, 'POST');
      assert.ok(calls[0].url.endsWith('/bookmarks'));
    }
  });

  it('returns the server\'s merged tag set rather than computing one', async () => {
    const { client } = api([{ status: 200, body: { id: 1, tags: ['fastapi', 'python'] } }]);
    const result = await client.save({ url: 'https://x.test/', tags: ['fastapi'] });
    assert.deepEqual(result.tags, ['fastapi', 'python']);
  });
});

describe('tag removal', () => {
  it('encodes tag names containing url-unsafe characters', async () => {
    const { client, calls } = api([{ status: 200, body: {} }]);
    await client.removeTag(7, 'c++');
    assert.ok(calls[0].url.endsWith('/bookmarks/7/tags/c%2B%2B'));
  });
});

describe('failure reporting', () => {
  it('turns an unreachable host into a readable message', async () => {
    const { client } = api([new TypeError('Failed to fetch')]);
    await assert.rejects(() => client.health(), (error) => {
      assert.ok(error.message.includes('Cannot reach https://example.test'));
      return true;
    });
  });

  it('explains 503 as the server refusing writes, not as being down', () => {
    assert.match(errorMessage(503, null), /no API tokens configured/i);
  });

  it('points 401 and 403 at the options page', () => {
    assert.match(errorMessage(401, null), /options/i);
    assert.match(errorMessage(403, null), /options/i);
  });

  it('prefers the server detail for 422', () => {
    assert.equal(errorMessage(422, { detail: "Tag 'x' exceeds…" }), "Tag 'x' exceeds…");
  });

  it('shows the first validation error, as the API sends them, for 422', () => {
    const payload = {
      detail: [
        {
          type: 'value_error',
          loc: ['body', 'tags'],
          msg: "Value error, tag 'a b': tag names cannot contain commas, whitespace or control characters",
        },
      ],
    };
    assert.equal(
      errorMessage(422, payload),
      "tag 'a b': tag names cannot contain commas, whitespace or control characters",
    );
  });

  it('falls back to a plain message for a 422 it cannot read', () => {
    assert.equal(errorMessage(422, { detail: [{}] }), 'The server could not accept that.');
  });

  it('survives an error response with no JSON body', async () => {
    const { client } = api([{ status: 500, body: null }]);
    await assert.rejects(() => client.health(), (error) => error.status === 500);
  });

  it('handles 204 with no body', async () => {
    const { client } = api([{ status: 204 }]);
    assert.equal(await client.removeTag(1, 'x'), null);
  });
});
