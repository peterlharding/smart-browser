/**
 * The API client, which runs in the main process and only there (ADR 0015).
 *
 * The token never reaches a renderer: the UI asks for lookups and saves over IPC, and this
 * makes them. Request and response shapes come from the generated contract types, so a
 * contract change that breaks the browser fails to compile.
 */

import type { components } from '../shared/api-types';
import type { Bookmark, Health, TagCount } from '../shared/ipc';

type BookmarkCreate = components['schemas']['BookmarkCreate'];

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /**
     * Nothing that is the API answered: it could not be reached, timed out, or something in
     * front of it (a proxy's 502, 503 or 504) answered in its place. A save that fails this
     * way waits in the queue; any other failure is the API's answer, and is said at once
     * (ADR 0017).
     */
    readonly offline = false,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Whether *error* means the API was away, rather than that it answered no. */
export function isOffline(error: unknown): boolean {
  return error instanceof ApiError && error.offline;
}

export interface ApiConfig {
  baseUrl: string;
  token: string;
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

const TIMEOUT_MS = 8000;

export class Api {
  private readonly baseUrl: string;

  constructor(
    private readonly config: ApiConfig,
    private readonly fetchImpl: Fetch = (input, init) => fetch(input, init),
  ) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, '');
  }

  health(): Promise<Health> {
    return this.request<Health>('/health', { auth: false });
  }

  /** Your save of *url*, or null when you have never saved it. */
  async lookup(url: string): Promise<Bookmark | null> {
    try {
      return await this.request<Bookmark>(`/bookmarks/lookup?url=${encodeURIComponent(url)}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }

  /** The one write on the save path: an upsert, merging tags (ADR 0006). */
  save(input: { url: string; title: string | null; tags: string[] }): Promise<Bookmark> {
    const body: BookmarkCreate = {
      url: input.url,
      title: input.title || null,
      saved_from: 'smart-browser',
      tags: input.tags,
    };
    return this.request<Bookmark>('/bookmarks', { method: 'POST', body });
  }

  removeTag(id: number, tag: string): Promise<Bookmark> {
    return this.request<Bookmark>(`/bookmarks/${id}/tags/${encodeURIComponent(tag)}`, {
      method: 'DELETE',
    });
  }

  /** Your tags with your usage counts, for autocomplete. */
  tags(): Promise<TagCount[]> {
    return this.request<TagCount[]>('/tags?min_count=1&limit=2000');
  }

  private async request<T>(
    path: string,
    { method = 'GET', body, auth = true }: { method?: string; body?: unknown; auth?: boolean } = {},
  ): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth) headers.Authorization = `Bearer ${this.config.token}`;

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/v1${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch (cause) {
      const because = cause instanceof Error ? cause.message : String(cause);
      throw new ApiError(`Cannot reach ${this.baseUrl}: ${because}`, 0, true);
    }

    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      // The API explains its own refusals in `detail`; a gateway's error page does not.
      const fromApi = detailOf(payload) !== null;
      const away = response.status === 502 || response.status === 504 || (response.status === 503 && !fromApi);
      throw new ApiError(away ? `Cannot reach ${this.baseUrl}: ${response.status} from something in front of it` : errorMessage(response.status, payload), response.status, away);
    }
    return payload as T;
  }
}

/** The server's own explanation, if it gave one: a string, or the first validation error. */
function detailOf(payload: unknown): string | null {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  const first = Array.isArray(detail) ? (detail[0] as { msg?: unknown } | undefined)?.msg : null;
  return typeof first === 'string' ? first.replace(/^Value error, /, '') : null;
}

/** Something worth reading in a save sheet, for each way a request can fail. */
export function errorMessage(status: number, payload: unknown): string {
  const detail = detailOf(payload);
  switch (status) {
    case 401:
      return 'No token sent. Check Settings.';
    case 403:
      return 'Token rejected. Check Settings.';
    case 404:
      return detail || 'Not found.';
    case 422:
      return detail || 'The server could not accept that.';
    case 503:
      return 'The server has no API tokens configured, so it is refusing requests.';
    default:
      return detail || `Request failed (${status}).`;
  }
}
