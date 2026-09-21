import { describe, expect, it } from 'vitest';

import { displayUrl, resolveInput } from '../../src/main/omnibox';

describe('resolveInput', () => {
  it.each([
    ['https://example.com/a', 'https://example.com/a'],
    ['HTTP://Example.com', 'http://example.com/'],
    ['example.com', 'https://example.com'],
    ['docs.python.org/3/library/', 'https://docs.python.org/3/library/'],
    ['node.js', 'https://node.js'],
    ['localhost:8085/api/v1/docs', 'http://localhost:8085/api/v1/docs'],
    ['127.0.0.1:8000', 'http://127.0.0.1:8000'],
    ['[::1]:8080/x', 'http://[::1]:8080/x'],
    ['about:blank', 'about:blank'],
    ['file:///Users/someone/notes.html', 'file:///Users/someone/notes.html'],
  ])('visits %s', (input, url) => {
    expect(resolveInput(input, 'duckduckgo')).toBe(url);
  });

  it.each([
    ['postgres work_mem', 'postgres%20work_mem'],
    ['3.14', '3.14'],
    ['javascript:alert(1)', 'javascript%3Aalert(1)'],
    ['data:text/html,hi', 'data%3Atext%2Fhtml%2Chi'],
    ['what is a.b', 'what%20is%20a.b'],
  ])('searches for %s rather than opening it', (input, encoded) => {
    expect(resolveInput(input, 'duckduckgo')).toBe(`https://duckduckgo.com/?q=${encoded}`);
  });

  it('searches with the engine chosen in settings', () => {
    expect(resolveInput('tags', 'google')).toBe('https://www.google.com/search?q=tags');
    expect(resolveInput('tags', 'bing')).toBe('https://www.bing.com/search?q=tags');
  });

  it('does nothing for blank input', () => {
    expect(resolveInput('   ', 'duckduckgo')).toBeNull();
  });
});

describe('displayUrl', () => {
  it('shows nothing for a new tab, and the address otherwise', () => {
    expect(displayUrl('about:blank')).toBe('');
    expect(displayUrl('https://example.com/')).toBe('https://example.com/');
  });
});
