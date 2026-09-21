import { describe, expect, it } from 'vitest';

import { historyUrl, hostOf, isInternal, isRecordable, isWeb, pageKey } from '../../src/main/urls';

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

describe('what kind of page a tab shows', () => {
  it('saves web pages only', () => {
    expect(isWeb('https://a.test/')).toBe(true);
    expect(isWeb('http://a.test/')).toBe(true);
    expect(isWeb('file:///tmp/a.html')).toBe(false);
    expect(isWeb('smart://history/')).toBe(false);
  });

  it('records web pages and files, never the browser’s own pages or a blank tab', () => {
    expect(isRecordable('https://a.test/')).toBe(true);
    expect(isRecordable('file:///tmp/a.html')).toBe(true);
    expect(isRecordable('smart://history/')).toBe(false);
    expect(isRecordable('about:blank')).toBe(false);
    expect(isRecordable('data:text/html,hi')).toBe(false);
  });

  it('knows the history page, and not the UI files served beside it', () => {
    expect(isInternal('smart://history/')).toBe(true);
    expect(isInternal('smart://history/?q=pg')).toBe(true);
    expect(isInternal('smart://ui/chrome.html')).toBe(false);
    expect(isInternal('https://history/')).toBe(false);
    expect(isInternal('not a url')).toBe(false);
  });
});

describe('historyUrl', () => {
  it('puts what the page shows in its address', () => {
    expect(historyUrl()).toBe('smart://history/');
    expect(historyUrl({ text: 'work mem', host: 'a.test' })).toBe('smart://history/?q=work+mem&host=a.test');
    expect(historyUrl({ day: '2026-09-21', panel: 'clear' })).toBe('smart://history/?day=2026-09-21&panel=clear');
  });
});

describe('hostOf', () => {
  it('is the host "More from this site" means, and nothing for a file', () => {
    expect(hostOf('https://www.a.test:8443/p')).toBe('www.a.test');
    expect(hostOf('file:///tmp/a.html')).toBe('');
  });
});
