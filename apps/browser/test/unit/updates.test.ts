import { describe, expect, it } from 'vitest';

import { CHECK_EVERY_MS, UPDATE_HOST, Updates, type Timers, type Updater } from '../../src/main/updates';

/** A stand-in for Electron's autoUpdater, and timers the test fires by hand. */
function setup(options: { packaged?: boolean; underTest?: boolean; automatic?: boolean } = {}) {
  const feeds: Array<{ url: string; headers: Record<string, string> }> = [];
  let checks = 0;
  let installs = 0;
  let downloaded: ((version: string) => void) | undefined;
  let failed: ((error: Error) => void) | undefined;
  const updater: Updater = {
    setFeedURL: (feed) => feeds.push(feed),
    checkForUpdates: () => (checks += 1),
    quitAndInstall: () => (installs += 1),
    onDownloaded: (listener) => (downloaded = listener),
    onError: (listener) => (failed = listener),
  };
  const scheduled: Array<{ ms: number; fire: () => void; cleared: boolean }> = [];
  const timers: Timers = {
    set: (callback, ms) => {
      const timer = { ms, fire: callback, cleared: false };
      scheduled.push(timer);
      return timer;
    },
    clear: (handle) => ((handle as { cleared: boolean }).cleared = true),
  };
  const logs: string[] = [];
  let changes = 0;
  const updates = new Updates(
    updater,
    {
      repo: 'owner/repo',
      version: '0.7.0',
      platform: 'darwin',
      arch: 'arm64',
      packaged: options.packaged ?? true,
      underTest: options.underTest ?? false,
      automatic: options.automatic ?? true,
    },
    () => (changes += 1),
    (message) => logs.push(message),
    timers,
  );
  return {
    updates,
    feeds,
    logs,
    checks: () => checks,
    installs: () => installs,
    changes: () => changes,
    download: (version: string) => downloaded?.(version),
    fail: (message: string) => failed?.(new Error(message)),
    pending: () => scheduled.filter((t) => !t.cleared),
  };
}

describe('Updates', () => {
  it('asks the service for the release that matches this build', () => {
    const { updates, feeds } = setup();
    updates.start();
    expect(feeds).toEqual([
      {
        url: `${UPDATE_HOST}/owner/repo/darwin-arm64/0.7.0`,
        headers: { 'User-Agent': 'Smart-Browser/0.7.0 (darwin: arm64)' },
      },
    ]);
  });

  it('checks at launch and every six hours', () => {
    const { updates, checks, pending } = setup();
    updates.start();
    expect(checks()).toBe(1);
    const timer = pending()[0]!;
    expect(timer.ms).toBe(CHECK_EVERY_MS);
    timer.fire();
    expect(checks()).toBe(2);
  });

  it('touches nothing in a build run from the repo, which offers no switch either', () => {
    const { updates, feeds, checks, pending } = setup({ packaged: false });
    updates.start();
    updates.checkNow();
    updates.setAutomatic(true);
    expect(feeds).toEqual([]);
    expect(checks()).toBe(0);
    expect(pending()).toEqual([]);
    expect(updates.current()).toEqual({ kind: 'off' });
    expect(updates.available()).toBe(false);
  });

  it('touches nothing under test, while still looking like the app that ships', () => {
    const { updates, feeds, checks } = setup({ underTest: true });
    updates.start();
    updates.checkNow();
    expect(feeds).toEqual([]);
    expect(checks()).toBe(0);
    expect(updates.available()).toBe(true); // the packaged app's Settings switch is there
  });

  it('checks nothing while the switch is off, and still knows where to ask', () => {
    const { updates, feeds, checks } = setup({ automatic: false });
    updates.start();
    expect(feeds).toHaveLength(1); // the feed costs no request
    expect(checks()).toBe(0);
    expect(updates.current()).toEqual({ kind: 'idle' });

    updates.checkNow(); // Check for Updates Now works either way
    expect(checks()).toBe(1);
  });

  it('starts and stops checking with the switch', () => {
    const { updates, checks, pending } = setup({ automatic: false });
    updates.start();
    updates.setAutomatic(true);
    expect(checks()).toBe(1);
    expect(pending()).toHaveLength(1);

    updates.setAutomatic(false);
    expect(pending()).toEqual([]);
    expect(checks()).toBe(1); // and nothing more
  });

  it('holds a downloaded update, and restarts into it when asked', () => {
    const { updates, changes, installs, download } = setup();
    updates.start();
    const before = changes();
    download('0.8.0');
    expect(updates.current()).toEqual({ kind: 'ready', version: '0.8.0' });
    expect(changes()).toBe(before + 1); // the menu and the toolbar follow

    updates.restartToInstall();
    expect(installs()).toBe(1);
  });

  it('restarts into nothing when no update is waiting', () => {
    const { updates, installs } = setup();
    updates.start();
    updates.restartToInstall();
    expect(installs()).toBe(0);
  });

  it('keeps a ready update through the switch being turned off', () => {
    const { updates, download } = setup();
    updates.start();
    download('0.8.0');
    updates.setAutomatic(false);
    expect(updates.current()).toEqual({ kind: 'ready', version: '0.8.0' });
  });

  it('says nothing to the user when a check fails, and keeps checking', () => {
    const { updates, logs, fail, pending } = setup();
    updates.start();
    fail('getaddrinfo ENOTFOUND update.electronjs.org');
    expect(updates.current()).toEqual({ kind: 'idle' });
    expect(logs.join('\n')).toContain('update check failed');
    expect(pending()).toHaveLength(1);
  });

  it('is started once, however often it is asked', () => {
    const { updates, feeds, checks } = setup();
    updates.start();
    updates.start();
    expect(feeds).toHaveLength(1);
    expect(checks()).toBe(1);
  });
});
