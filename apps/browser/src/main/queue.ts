/**
 * Saves made while the API was away, delivered when it is back (ADR 0017).
 *
 * The saves themselves are kept in history.db; this decides when to deliver them. One for
 * the app, however many windows: it delivers the oldest first, one at a time, stops at the
 * first sign the API is still away, and moves past a save the API refuses, which then
 * waits for you rather than for the API.
 *
 * Delivering a save twice is harmless, since a save is an upsert keyed by the page, so
 * this needs no more than at-least-once. It never asks the API while nothing waits.
 */

import type { Delivery } from '../shared/ipc';
import type { Api } from './api';
import { isOffline } from './api';
import type { History } from './history';

/** How long to wait before trying again, in minutes, then the last one for good. */
export const RETRY_MINUTES = [1, 2, 5, 10];

export interface Timers {
  set(callback: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const realTimers: Timers = {
  set: (callback, ms) => setTimeout(callback, ms),
  clear: (handle) => clearTimeout(handle as NodeJS.Timeout),
};

export class SaveQueue {
  private running: Promise<Delivery> | null = null;
  private timer: unknown = null;
  private step = 0;
  private stopped = false;

  constructor(
    private readonly history: History,
    private readonly connection: { connect(): Promise<Api | string | null> },
    private readonly timers: Timers = realTimers,
  ) {}

  /**
   * Keep a save for later, and try again in a minute, or when the schedule next says.
   * *failed* is why the save just tried could not go: that was its first attempt.
   */
  add(save: { url: string; title: string; tags: string[] }, { replace = false, failed }: { replace?: boolean; failed?: string } = {}): void {
    this.history.queueSave(save, { replace });
    const queued = failed ? this.history.pendingFor(save.url) : null;
    if (queued && failed) this.history.stillWaiting(queued.id, failed);
    if (this.timer === null) this.schedule();
  }

  /** At launch: deliver what waited while the browser was closed. */
  start(): void {
    if (this.waiting()) void this.flush();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
  }

  /** Try refused saves again, one or all, and deliver now. */
  retry(id?: number): Promise<Delivery> {
    this.history.unrefuse(id);
    return this.flush();
  }

  drop(id: number): void {
    this.history.dropPending(id);
    if (!this.waiting()) this.cancel();
  }

  /** Deliver now: a second call while one runs joins it. Asks nothing if nothing waits. */
  flush(): Promise<Delivery> {
    if (!this.waiting()) return Promise.resolve('nothing');
    this.running ??= this.deliver().finally(() => {
      this.running = null;
    });
    return this.running;
  }

  private waiting(): boolean {
    return this.history.pendingSaves().some((save) => !save.refused);
  }

  private async deliver(): Promise<Delivery> {
    const api = await this.connection.connect();
    if (api === null || typeof api === 'string') {
      // No API configured, or one that speaks another contract: the schedule keeps asking,
      // cheaply, since nothing is sent until Settings change.
      this.schedule();
      return 'blocked';
    }
    for (const save of this.history.pendingSaves()) {
      if (save.refused) continue;
      try {
        const saved = await api.save({ url: save.url, title: save.title, tags: save.tags });
        this.history.delivered(save, saved.tags);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (isOffline(error)) {
          this.history.stillWaiting(save.id, message);
          this.schedule();
          return 'offline';
        }
        this.history.refused(save.id, message);
      }
    }
    // Tags queued during the delivery are still waiting: go round again for them.
    if (this.waiting()) return this.deliver();
    this.cancel();
    return 'delivered';
  }

  /** The next try, further off each time the API is found still away. */
  private schedule(): void {
    if (this.stopped) return;
    if (this.timer !== null) this.timers.clear(this.timer);
    const minutes = RETRY_MINUTES[Math.min(this.step, RETRY_MINUTES.length - 1)]!;
    this.step += 1;
    this.timer = this.timers.set(() => {
      this.timer = null;
      void this.flush();
    }, minutes * 60_000);
  }

  private cancel(): void {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
    this.step = 0;
  }
}
