/**
 * Client for Smart-Browser API v2.
 *
 * `fetch` is injected rather than closed over, so the whole client is testable under
 * `node --test` with no browser and no network.
 */

export class ApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Raised when settings are missing, so the popup can send the user to the options page. */
export class NotConfigured extends ApiError {
  constructor(message) {
    super(message, { status: 0 });
    this.name = 'NotConfigured';
  }
}

export class BookmarksApi {
  constructor({ baseUrl, token, fetchImpl = globalThis.fetch }) {
    this.baseUrl = (baseUrl || '').replace(/\/+$/, '');
    this.token = token || '';
    this.fetch = fetchImpl;
  }

  get configured() {
    return Boolean(this.baseUrl && this.token);
  }

  async #request(path, { method = 'GET', body, auth = false } = {}) {
    if (!this.baseUrl) throw new NotConfigured('No API address configured.');
    if (auth && !this.token) throw new NotConfigured('No API token configured.');

    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth) headers.Authorization = `Bearer ${this.token}`;

    let response;
    try {
      response = await this.fetch(`${this.baseUrl}/api/v2${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (cause) {
      throw new ApiError(`Cannot reach ${this.baseUrl}`, { detail: String(cause) });
    }

    if (response.status === 204) return null;

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      throw new ApiError(errorMessage(response.status, payload), {
        status: response.status,
        detail: payload?.detail ?? null,
      });
    }
    return payload;
  }

  /**
   * The page's current state in *your* library, or null when you have never saved it.
   *
   * Authenticated, because the answer is per-user: someone else having saved a page tells
   * you nothing, and must not tell you anything.
   */
  async lookup(url) {
    try {
      return await this.#request(`/bookmarks/lookup?url=${encodeURIComponent(url)}`, {
        auth: true,
      });
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  }

  /**
   * Upsert. 201 when the bookmark is created, 200 when it already existed; tags are
   * merged either way. This is the only write on the save path -- the caller never has
   * to know which case it is, and cannot race between finding out and acting on it.
   */
  save({ url, title, tags = [] }) {
    return this.#request('/bookmarks', {
      method: 'POST',
      auth: true,
      body: { url, title, saved_from: 'chrome-extension', tags },
    });
  }

  removeTag(id, tag) {
    return this.#request(`/bookmarks/${id}/tags/${encodeURIComponent(tag)}`, {
      method: 'DELETE',
      auth: true,
    });
  }

  /** Your tags with your usage counts, for autocomplete. Authenticated for the same reason. */
  tags({ minCount = 0, limit = 500 } = {}) {
    return this.#request(`/tags?min_count=${minCount}&limit=${limit}`, { auth: true });
  }

  /** Liveness and compatibility. The one call that needs no credential. */
  health() {
    return this.#request('/health');
  }
}

/** Turn a status code into something worth reading in a 360px popup. */
export function errorMessage(status, payload) {
  const detail = typeof payload?.detail === 'string' ? payload.detail : null;
  switch (status) {
    case 401:
      return 'No token sent. Check the extension options.';
    case 403:
      return 'Token rejected. Check the extension options.';
    case 404:
      return 'Not found.';
    case 422:
      return detail || 'The server could not accept that.';
    case 503:
      return 'The server has no API tokens configured, so it is refusing writes.';
    default:
      return detail || `Request failed (${status}).`;
  }
}
