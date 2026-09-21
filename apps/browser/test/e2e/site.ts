/**
 * A local site for the end-to-end tests: pages with titles, a favicon, a link that opens
 * a new window, and one with no title at all. Served on 127.0.0.1, so no test touches the
 * internet.
 */

import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

const FAVICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" rx="3" fill="#0f766e"/><path d="M4 8h8" stroke="#fff" stroke-width="2"/></svg>';

const page = (title: string | null, body: string) =>
  `<!doctype html><html><head><meta charset="utf-8">${title === null ? '' : `<title>${title}</title>`}` +
  `<link rel="icon" href="/favicon.svg"></head><body style="font:16px system-ui;margin:32px">${body}</body></html>`;

const PAGES: Record<string, string> = {
  '/article.html': page(
    'Tuning Postgres',
    '<h1>Tuning Postgres</h1><p>Work memory matters more than shared buffers for sorts.</p>',
  ),
  '/links.html': page(
    'Links',
    '<h1>Links</h1><p><a id="blank" href="/second.html" target="_blank">Open the second page</a></p>',
  ),
  '/second.html': page('Second page', '<h1>Second page</h1>'),
  '/untitled.html': page(null, '<p>No title here.</p>'),
};

export function startSite(): Promise<{ server: Server; url: string }> {
  const server = createServer((request, response) => {
    const path = new URL(request.url ?? '/', 'http://site').pathname;
    if (path === '/favicon.svg') {
      response.writeHead(200, { 'Content-Type': 'image/svg+xml' }).end(FAVICON);
      return;
    }
    const body = PAGES[path];
    if (!body) {
      response.writeHead(404, { 'Content-Type': 'text/html' }).end(page('Not found', 'Not found'));
      return;
    }
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(body);
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as AddressInfo;
      resolve({ server, url: `http://127.0.0.1:${port}` });
    });
  });
}
