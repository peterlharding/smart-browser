<script lang="ts">
  // File > Saves Waiting: pages saved while the bookmarks API was away, still to be
  // delivered, and any it refused when it came back, each to retry or drop (ADR 0017).
  // The main process sends the list afresh as deliveries happen.

  import type { Delivery, PendingSave } from '../shared/ipc';
  import { overlayApi } from './bridge';

  let { saves }: { saves: PendingSave[] } = $props();

  const smart = overlayApi();
  let busy = $state(false);
  let status: string | null = $state(null);
  let first: HTMLButtonElement | undefined = $state();

  $effect(() => {
    first?.focus();
  });

  const timeFormat = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    hour: 'numeric',
    minute: '2-digit',
  });

  const said: Record<Delivery, string | null> = {
    nothing: null,
    delivered: null,
    offline: 'Still can’t reach your bookmarks API.',
    blocked: 'Saving is off: check Settings.',
  };

  async function retry(id?: number) {
    busy = true;
    status = said[await smart.retry(id)];
    busy = false;
  }

  function hostOf(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url;
    }
  }

  function tried(save: PendingSave): string {
    const parts = [`Saved ${timeFormat.format(save.savedAt)}`];
    if (save.attempts) parts.push(`tried ${save.attempts === 1 ? 'once' : `${save.attempts} times`}`);
    if (save.lastError) parts.push(save.lastError);
    return parts.join(' · ');
  }
</script>

<h1>Saves waiting</h1>
<p class="intro">Saved while your bookmarks API was away. They go as soon as it answers.</p>

<ul aria-label="Saves waiting">
  {#each saves as save (save.id)}
    <li class:refused={save.refused}>
      <div class="page">
        <span class="title" title={save.url}>{save.title || save.url}</span>
        <span class="site">{hostOf(save.url)}</span>
      </div>
      {#if save.tags.length}
        <div class="tags">
          {#each save.tags as tag (tag)}<span class="tag">{tag}</span>{/each}
        </div>
      {/if}
      <div class="meta">
        {#if save.refused}
          <span class="reason">Refused: {save.lastError}</span>
        {:else}
          <span title={save.lastError ?? undefined}>{tried(save)}</span>
        {/if}
      </div>
      <div class="actions">
        <button class="link" disabled={busy} onclick={() => retry(save.id)}>Retry</button>
        <button class="link" onclick={() => smart.drop(save.id)}>Drop</button>
      </div>
    </li>
  {/each}
</ul>

{#if status}
  <p class="status" role="status">{status}</p>
{/if}

<footer>
  <button class="secondary" onclick={() => smart.close()}>Close</button>
  <button class="primary" bind:this={first} disabled={busy} onclick={() => retry()}>Retry all</button>
</footer>

<style>
  h1 {
    margin: 0 0 4px;
    font-size: 15px;
    font-weight: 600;
  }

  .intro {
    margin: 0 0 12px;
    color: var(--text-muted);
    font-size: 12px;
  }

  ul {
    display: grid;
    gap: 8px;
    max-height: 360px;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    list-style: none;
  }

  li {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px 12px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
  }

  li.refused {
    border-color: var(--danger);
  }

  .page {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }

  .title {
    overflow: hidden;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .site {
    flex: none;
    color: var(--text-muted);
    font-size: 12px;
  }

  .tags {
    display: flex;
    flex-wrap: wrap;
    grid-column: 1;
    gap: 4px;
  }

  .tag {
    padding: 1px 7px;
    border: 1px solid var(--chip-border);
    border-radius: 10px;
    background: var(--chip);
    font-size: 11px;
  }

  .meta {
    grid-column: 1;
    min-width: 0;
    overflow: hidden;
    color: var(--text-muted);
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .reason {
    color: var(--danger);
    white-space: normal;
  }

  .actions {
    display: flex;
    grid-column: 2;
    grid-row: 1;
    gap: 10px;
  }

  .link {
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    font-size: 12px;
    font-weight: 600;
  }

  .link:disabled {
    opacity: 0.5;
  }

  .status {
    margin: 10px 0 0;
    color: var(--warn);
    font-size: 12px;
  }

  footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 14px;
  }

  footer button {
    height: 30px;
    padding: 0 14px;
    border-radius: 8px;
    font-weight: 600;
  }

  .secondary {
    border: 1px solid var(--border);
    background: var(--card);
  }

  .primary {
    border: 0;
    background: var(--accent);
    color: #fff;
  }

  .primary:disabled {
    opacity: 0.6;
  }
</style>
