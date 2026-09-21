<script lang="ts">
  // Settings: where the bookmarks API is, the token for it, and the search engine. The
  // token goes to the main process and is stored by the operating system's secret store;
  // it is never shown again, only replaced (ADR 0015).

  import type { ConnectionReport, SearchEngine, SettingsInput, SettingsView } from '../shared/ipc';
  import { overlayApi } from './bridge';

  let { settings }: { settings: SettingsView } = $props();

  const smart = overlayApi();
  // Seeded once, then edited here: the form must not be reset under the person typing.
  // svelte-ignore state_referenced_locally
  let apiUrl = $state(settings.apiUrl);
  let token = $state('');
  // svelte-ignore state_referenced_locally
  let searchEngine: SearchEngine = $state(settings.searchEngine);
  let report: ConnectionReport | null = $state(null);
  let first: HTMLInputElement | undefined = $state();

  // autofocus only acts when a page loads; this card is mounted into one already loaded.
  $effect(() => {
    first?.focus();
  });
  let testing = $state(false);
  let problem: string | null = $state(null);

  const engines: { value: SearchEngine; label: string }[] = [
    { value: 'duckduckgo', label: 'DuckDuckGo' },
    { value: 'google', label: 'Google' },
    { value: 'bing', label: 'Bing' },
  ];

  function input(): SettingsInput {
    // A blank token field keeps the stored token rather than removing it.
    return token.trim() ? { apiUrl, token, searchEngine } : { apiUrl, searchEngine };
  }

  async function test() {
    testing = true;
    report = await smart.testConnection(input());
    testing = false;
  }

  async function save() {
    try {
      await smart.saveSettings(input());
    } catch (error) {
      problem = error instanceof Error ? error.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '') : String(error);
    }
  }
</script>

<h1>Settings</h1>

<form onsubmit={(e) => { e.preventDefault(); void save(); }}>
  <label>
    <span>Bookmarks API</span>
    <input bind:this={first} bind:value={apiUrl} placeholder="http://127.0.0.1:8000" spellcheck="false" autocomplete="off" />
  </label>

  <label>
    <span>API token</span>
    <input
      type="password"
      bind:value={token}
      placeholder={settings.hasToken ? 'Stored in the Keychain; leave blank to keep it' : 'The token half of an API_TOKENS entry'}
      autocomplete="off"
    />
  </label>
  {#if settings.tokenStorage === 'unavailable'}
    <p class="problem">This system has no secret store, so a token cannot be kept.</p>
  {/if}

  <label>
    <span>Search with</span>
    <select bind:value={searchEngine}>
      {#each engines as engine (engine.value)}
        <option value={engine.value}>{engine.label}</option>
      {/each}
    </select>
  </label>

  {#if report}
    <p class="report" class:ok={report.ok && report.compatible} class:bad={!report.ok || !report.compatible} role="status">
      {#if report.ok}
        Connected: API {report.version}, contract {report.contract}, schema {report.schema ?? 'unknown'}.
        {#if !report.compatible}This browser needs contract 1, so saving will stay off.{/if}
      {:else}
        {report.reason}
      {/if}
    </p>
  {/if}
  {#if problem}
    <p class="problem" role="alert">{problem}</p>
  {/if}

  <footer>
    <button type="button" class="secondary" disabled={testing} onclick={test}>
      {testing ? 'Testing…' : 'Test connection'}
    </button>
    <span class="spacer"></span>
    <button type="button" class="secondary" onclick={() => smart.close()}>Cancel</button>
    <button type="submit" class="primary">Save</button>
  </footer>
</form>

<style>
  h1 {
    margin: 0 0 14px;
    font-size: 15px;
    font-weight: 600;
  }

  label {
    display: grid;
    gap: 5px;
    margin-bottom: 12px;
  }

  label span {
    color: var(--text-muted);
    font-size: 12px;
    font-weight: 600;
  }

  input,
  select {
    width: 100%;
    height: 32px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--field-focus);
    outline: none;
  }

  /* A native select pads its text a few pixels more than an input; line them up. */
  select {
    padding-left: 6px;
  }

  input:focus,
  select:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .report,
  .problem {
    margin: 2px 0 12px;
    font-size: 12px;
  }

  .report.ok {
    color: var(--text-muted);
  }

  .report.bad,
  .problem {
    color: var(--danger);
  }

  footer {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }

  .spacer {
    flex: 1;
  }

  button {
    height: 30px;
    padding: 0 14px;
    border-radius: 8px;
    font-weight: 600;
  }

  .secondary {
    border: 1px solid var(--border);
    background: var(--card);
  }

  .secondary:hover:not(:disabled) {
    background: var(--hover);
  }

  .primary {
    border: 0;
    background: var(--accent);
    color: #fff;
  }
</style>
