import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { contextMenuTarget } from '../src/lib/quicksave.js';

const tab = { id: 7, url: 'https://news.example/front', title: 'Front page - News' };

describe('contextMenuTarget', () => {
  it('saves a link without the tab title, which belongs to the linking page', () => {
    const target = contextMenuTarget({ linkUrl: 'https://blog.example/post', pageUrl: tab.url }, tab);
    assert.deepEqual(target, { url: 'https://blog.example/post', title: undefined, tabId: 7 });
  });

  it('saves the page itself with the title the tab shows', () => {
    const target = contextMenuTarget({ pageUrl: tab.url }, tab);
    assert.deepEqual(target, { url: tab.url, title: 'Front page - News', tabId: 7 });
  });

  it('falls back to the tab url when the menu reports no page url', () => {
    assert.equal(contextMenuTarget({}, tab).url, tab.url);
  });
});
