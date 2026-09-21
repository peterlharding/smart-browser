/**
 * The real stack for the end-to-end tests: the test database migrated from nothing, the
 * API under uvicorn with a throwaway token, and the local site. Torn down afterwards.
 *
 * TEST_DATABASE_URL must name a database ending in `_test`; `make test-browser-e2e`
 * derives it from .env the way `make test-pg` does, and refuses the real one.
 */

import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';

import { startSite } from './site';

const ROOT = fileURLToPath(new URL('../../../../', import.meta.url));

function databaseEnv(): Record<string, string> {
  const raw = process.env.TEST_DATABASE_URL;
  if (!raw) throw new Error('TEST_DATABASE_URL is not set; run this through `make test-browser-e2e`.');
  const url = new URL(raw.replace(/^postgresql\+\w+:/, 'postgresql:'));
  const name = url.pathname.slice(1);
  if (!name.endsWith('_test')) {
    throw new Error(`Refusing ${name}: the end-to-end tests drop its tables. Use a *_test database.`);
  }
  return {
    DB_HOST: url.hostname,
    DB_PORT: url.port || '5432',
    DB_USER: decodeURIComponent(url.username),
    DB_PASSWORD: decodeURIComponent(url.password),
    DB_NAME: name,
  };
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address() as { port: number };
      server.close(() => resolve(port));
    });
  });
}

async function waitFor(url: string, deadline = Date.now() + 30_000): Promise<void> {
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`${url} did not come up`);
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  const env = { ...process.env, ...databaseEnv() };
  const alembic = (...args: string[]) =>
    execFileSync('uv', ['--project', 'db', 'run', 'alembic', '-c', 'db/alembic.ini', ...args], {
      cwd: ROOT,
      env,
      stdio: 'pipe',
    });
  alembic('downgrade', 'base');
  alembic('upgrade', 'head');

  const token = randomUUID();
  const port = await freePort();
  const api: ChildProcess = spawn(
    'uv',
    ['--project', 'apps/api', 'run', 'uvicorn', 'bookmarks_api.main:app', '--port', String(port)],
    { cwd: ROOT, env: { ...env, API_TOKENS: `e2e:${token}` }, stdio: 'ignore' },
  );
  const apiUrl = `http://127.0.0.1:${port}`;
  await waitFor(`${apiUrl}/api/v1/health`);

  const site = await startSite();

  process.env.E2E_API_URL = apiUrl;
  process.env.E2E_API_TOKEN = token;
  process.env.E2E_SITE = site.url;

  return async () => {
    api.kill();
    site.server.close();
    alembic('downgrade', 'base');
  };
}
