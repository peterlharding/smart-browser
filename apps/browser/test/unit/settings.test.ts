import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { readSession, writeSession } from '../../src/main/session';
import { SettingsStore, type Secrets } from '../../src/main/settings';

// Reversible and visibly not plaintext, so a test can tell the token was encrypted.
const secrets = (available = true): Secrets => ({
  available: () => available,
  describe: () => 'backend: basic_text',
  encrypt: (text) => Buffer.from(`enc:${[...text].reverse().join('')}`),
  decrypt: (data) => [...data.toString().replace(/^enc:/, '')].reverse().join(''),
});

const file = () => join(mkdtempSync(join(tmpdir(), 'smart-settings-')), 'settings.json');

describe('SettingsStore', () => {
  it('starts empty, with DuckDuckGo', () => {
    const store = new SettingsStore(file(), secrets());
    expect([store.apiUrl, store.searchEngine, store.hasToken, store.token()]).toEqual(['', 'duckduckgo', false, null]);
  });

  it('keeps the token encrypted, never in the clear', () => {
    const path = file();
    new SettingsStore(path, secrets()).update({ apiUrl: 'http://api.test/', token: 's3cret', searchEngine: 'google' });
    expect(readFileSync(path, 'utf8')).not.toContain('s3cret');

    const reopened = new SettingsStore(path, secrets());
    expect([reopened.apiUrl, reopened.searchEngine, reopened.token()]).toEqual(['http://api.test', 'google', 's3cret']);
  });

  it('keeps the stored token when none is given, and removes it when given an empty one', () => {
    const store = new SettingsStore(file(), secrets());
    store.update({ apiUrl: 'http://api.test', token: 's3cret', searchEngine: 'duckduckgo' });
    store.update({ apiUrl: 'http://other.test', searchEngine: 'duckduckgo' });
    expect(store.token()).toBe('s3cret');
    store.update({ apiUrl: 'http://other.test', token: '  ', searchEngine: 'duckduckgo' });
    expect(store.hasToken).toBe(false);
  });

  it('refuses to keep a token where there is no secret store, rather than write it plain', () => {
    const store = new SettingsStore(file(), secrets(false));
    expect(() => store.update({ apiUrl: 'x', token: 's3cret', searchEngine: 'duckduckgo' })).toThrow(
      /no secret store \(backend: basic_text\)/,
    );
    expect(store.hasToken).toBe(false);
  });

  it('survives a settings file that is not JSON', async () => {
    const path = file();
    const { writeFileSync } = await import('node:fs');
    writeFileSync(path, '{ not json');
    expect(new SettingsStore(path, secrets()).searchEngine).toBe('duckduckgo');
  });
});

describe('session', () => {
  it('round-trips the open tabs and which was active', () => {
    const path = file();
    writeSession(path, { urls: ['https://a.test/', 'https://b.test/'], active: 1 });
    expect(readSession(path)).toEqual({ urls: ['https://a.test/', 'https://b.test/'], active: 1 });
  });

  it('reopens only pages worth reopening, and keeps the active index in range', () => {
    const path = file();
    writeSession(path, { urls: ['about:blank', 'https://a.test/', 'chrome://gpu'], active: 7 });
    expect(readSession(path)).toEqual({ urls: ['https://a.test/'], active: 0 });
  });

  it('has nothing to restore from nothing', () => {
    expect(readSession(join(tmpdir(), 'no-such-session.json'))).toBeNull();
  });
});
