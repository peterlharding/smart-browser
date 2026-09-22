/**
 * The bookmarks API as Settings name it, and whether it speaks this browser's contract
 * (ADR 0005). One for the app: every window and the save queue ask the same API, and the
 * contract is asked once a session, on the first thing that needs the API (ADR 0016).
 */

import { API_CONTRACT_VERSION } from '../shared/ipc';
import { Api, type ApiConfig } from './api';

export interface ConnectionSettings {
  readonly apiUrl: string;
  token(): string | null;
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

export class Connection {
  /** What /health said of the contract, for the address it was asked at. */
  private contract: { apiUrl: string; problem: string | null } | null = null;
  /** A /health already being asked, shared: the queue and an action often ask together. */
  private asking: Promise<void> | null = null;

  constructor(
    private readonly settings: ConnectionSettings,
    private readonly fetchImpl?: Fetch,
  ) {}

  /** The API Settings name, or null when they name none. Asks nothing. */
  api(): Api | null {
    const token = this.settings.token();
    if (!this.settings.apiUrl || !token) return null;
    const config: ApiConfig = { baseUrl: this.settings.apiUrl, token };
    return this.fetchImpl ? new Api(config, this.fetchImpl) : new Api(config);
  }

  /** Why saving is off, if the API was found to speak another contract. */
  problem(): string | null {
    return this.contract?.apiUrl === this.settings.apiUrl ? this.contract.problem : null;
  }

  /**
   * The API, for something you asked for: null when none is configured, or why it cannot
   * be used. The first call asks /health for the contract; an API that does not answer is
   * asked again next time, and the request itself says what went wrong.
   */
  async connect(): Promise<Api | string | null> {
    const api = this.api();
    if (!api) return null;
    const apiUrl = this.settings.apiUrl;
    if (this.contract?.apiUrl !== apiUrl) {
      this.asking ??= this.askContract(api, apiUrl).finally(() => {
        this.asking = null;
      });
      await this.asking;
    }
    return this.problem() ?? api;
  }

  private async askContract(api: Api, apiUrl: string): Promise<void> {
    try {
      const health = await api.health();
      this.contract = {
        apiUrl,
        problem:
          health.contract === API_CONTRACT_VERSION
            ? null
            : `The API speaks contract ${health.contract} and this browser speaks ` +
              `${API_CONTRACT_VERSION}, so saving is off until one of them is updated.`,
      };
    } catch {
      // Unreachable is reported by the request itself, where it can be retried.
    }
  }

  /** New settings may name another API: ask it afresh. */
  reset(): void {
    this.contract = null;
  }
}
