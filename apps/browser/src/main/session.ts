/**
 * The open tabs, so the next launch starts where this one stopped (ADR 0015).
 */

import { readFileSync } from 'node:fs';

import { write } from './settings';

export interface Session {
  urls: string[];
  active: number;
}

// Only pages worth reopening: web pages, files and the history page (ADR 0016). A crashed
// renderer's error page, or the browser's UI files, are not.
const RESTORABLE = /^(https?:|file:|smart:\/\/history\/)/i;

export function readSession(file: string): Session | null {
  try {
    const raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<Session>;
    const urls = Array.isArray(raw.urls)
      ? raw.urls.filter((u): u is string => typeof u === 'string' && RESTORABLE.test(u))
      : [];
    if (!urls.length) return null;
    const active = Number.isInteger(raw.active) ? Math.min(Math.max(raw.active as number, 0), urls.length - 1) : 0;
    return { urls, active };
  } catch {
    return null;
  }
}

export function writeSession(file: string, session: Session): void {
  write(file, session);
}
