/**
 * The browser's settings, kept in the user-data directory, with the API token encrypted
 * by the operating system's secret store (ADR 0015): the Keychain on macOS.
 *
 * The secret store is a parameter, so the store is tested without Electron; in the app it
 * is `safeStorage`. If the store is unavailable the token is not kept at all, rather than
 * written in the clear.
 */

import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

import type { SearchEngine, SettingsInput } from '../shared/ipc';

export interface Secrets {
  available(): boolean;
  /** Which store the platform chose, for saying why none is available. */
  describe(): string;
  encrypt(text: string): Buffer;
  decrypt(data: Buffer): string;
}

interface Stored {
  apiUrl: string;
  searchEngine: SearchEngine;
  token: string | null; // base64 of the encrypted token
}

const DEFAULTS: Stored = { apiUrl: '', searchEngine: 'duckduckgo', token: null };
const ENGINES: readonly SearchEngine[] = ['duckduckgo', 'google', 'bing'];

export class SettingsStore {
  private stored: Stored;

  constructor(
    private readonly file: string,
    private readonly secrets: Secrets,
  ) {
    this.stored = read(file);
  }

  get apiUrl(): string {
    return this.stored.apiUrl;
  }

  get searchEngine(): SearchEngine {
    return this.stored.searchEngine;
  }

  get hasToken(): boolean {
    return this.stored.token !== null;
  }

  get tokenStorageAvailable(): boolean {
    return this.secrets.available();
  }

  /** The decrypted token, or null when there is none or it can no longer be decrypted. */
  token(): string | null {
    if (this.stored.token === null) return null;
    try {
      return this.secrets.decrypt(Buffer.from(this.stored.token, 'base64'));
    } catch {
      return null;
    }
  }

  update(input: SettingsInput): void {
    const next: Stored = {
      apiUrl: input.apiUrl.trim().replace(/\/+$/, ''),
      searchEngine: ENGINES.includes(input.searchEngine) ? input.searchEngine : 'duckduckgo',
      token: this.stored.token,
    };
    if (input.token !== undefined) {
      const token = input.token.trim();
      if (!token) {
        next.token = null;
      } else if (!this.secrets.available()) {
        throw new Error(
          `This system has no secret store (${this.secrets.describe()}), so the token ` +
            'cannot be kept safely.',
        );
      } else {
        next.token = this.secrets.encrypt(token).toString('base64');
      }
    }
    write(this.file, next);
    this.stored = next;
  }
}

function read(file: string): Stored {
  try {
    const raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<Stored>;
    return {
      apiUrl: typeof raw.apiUrl === 'string' ? raw.apiUrl : DEFAULTS.apiUrl,
      searchEngine: ENGINES.includes(raw.searchEngine as SearchEngine)
        ? (raw.searchEngine as SearchEngine)
        : DEFAULTS.searchEngine,
      token: typeof raw.token === 'string' ? raw.token : null,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

/** Written to a temporary file and renamed, so a crash never leaves half a settings file. */
export function write(file: string, value: unknown): void {
  mkdirSync(dirname(file), { recursive: true });
  const temporary = `${file}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  renameSync(temporary, file);
}
