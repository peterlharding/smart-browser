/**
 * Updating itself, quietly (ADR 0019).
 *
 * Electron's autoUpdater against update.electronjs.org, which serves the signed zip of
 * the latest GitHub release (ADR 0018). A downloaded update is applied at the next launch
 * whether or not anything asks for a restart, so nothing here interrupts browsing: the
 * menu and the toolbar say an update is waiting, and that is all.
 *
 * The updater is a parameter, so the tests drive every state without a network or a
 * packaged app.
 */

export const UPDATE_HOST = 'https://update.electronjs.org';
/** At launch, then this often, while the switch is on. */
export const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;

/** What the browser knows about an update. */
export type UpdateState =
  | { kind: 'off' }
  | { kind: 'idle' }
  | { kind: 'ready'; version: string };

/** The part of Electron's autoUpdater this uses, so a test can stand in for it. */
export interface Updater {
  setFeedURL(feed: { url: string; headers: Record<string, string> }): void;
  checkForUpdates(): void;
  quitAndInstall(): void;
  onDownloaded(listener: (version: string) => void): void;
  onError(listener: (error: Error) => void): void;
}

export interface UpdatesOptions {
  /** "owner/repo" on GitHub, whose latest release is what the service serves. */
  repo: string;
  version: string;
  platform: string;
  arch: string;
  /**
   * A packaged build, which is the only kind that can replace itself. It decides what
   * Settings offers: a build run from the repo shows no update switch at all.
   */
  packaged: boolean;
  /**
   * Under test. A packaged app is what the end-to-end suite runs, and no test may reach
   * the service (ADR 0019), so checking is off while everything else looks as it ships.
   */
  underTest: boolean;
  /** The Settings switch, "Check for updates automatically". */
  automatic: boolean;
}

export interface Timers {
  set(callback: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

const realTimers: Timers = {
  set: (callback, ms) => setInterval(callback, ms),
  clear: (handle) => clearInterval(handle as NodeJS.Timeout),
};

export class Updates {
  private state: UpdateState = { kind: 'off' };
  private timer: unknown = null;
  private started = false;

  constructor(
    private readonly updater: Updater,
    private readonly options: UpdatesOptions,
    /** Something changed: the menu and the toolbar follow. */
    private readonly changed: () => void = () => {},
    private readonly log: (message: string) => void = () => {},
    private readonly timers: Timers = realTimers,
  ) {}

  current(): UpdateState {
    return this.state;
  }

  /** Whether this build could update itself: what Settings shows a switch for. */
  available(): boolean {
    return this.options.packaged;
  }

  private get enabled(): boolean {
    return this.options.packaged && !this.options.underTest;
  }

  /**
   * Point the updater at the service and start checking, if the switch is on. The feed is
   * set either way, so Check for Updates Now works with automatic checks off — setting it
   * asks nothing of the service.
   */
  start(): void {
    if (!this.enabled || this.started) return;
    this.started = true;
    const { repo, platform, arch, version } = this.options;
    this.updater.setFeedURL({
      url: `${UPDATE_HOST}/${repo}/${platform}-${arch}/${version}`,
      headers: { 'User-Agent': `Smart-Browser/${version} (${platform}: ${arch})` },
    });
    this.updater.onDownloaded((next) => {
      this.log(`update ${next} downloaded; it is applied at the next launch`);
      this.state = { kind: 'ready', version: next };
      this.changed();
    });
    // An update service that cannot be reached is not yours to fix: the next check tries
    // again, and nothing is shown.
    this.updater.onError((error) => this.log(`update check failed: ${error.message}`));
    this.state = { kind: 'idle' };
    if (this.options.automatic) this.schedule();
    this.changed();
  }

  /** The Settings switch. Off stops the checking at once; a ready update stays ready. */
  setAutomatic(automatic: boolean): void {
    this.options.automatic = automatic;
    if (!this.enabled || !this.started) return;
    if (automatic) this.schedule();
    else this.cancel();
  }

  /** Check for Updates Now: on whether or not automatic checking is on. */
  checkNow(): void {
    if (!this.enabled || !this.started) return;
    this.updater.checkForUpdates();
  }

  /** Restart into the update already downloaded. */
  restartToInstall(): void {
    if (this.state.kind !== 'ready') return;
    this.updater.quitAndInstall();
  }

  stop(): void {
    this.cancel();
  }

  private schedule(): void {
    this.cancel();
    this.updater.checkForUpdates();
    this.timer = this.timers.set(() => this.updater.checkForUpdates(), CHECK_EVERY_MS);
  }

  private cancel(): void {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
  }
}
