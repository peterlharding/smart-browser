<script lang="ts">
  // The save sheet, ⌘⇧B: whether this page is saved and with which tags, autocomplete from
  // your own vocabulary ranked by use, and one keystroke to save. The tag rules are the
  // extension's own code, imported (ADR 0015).
  //
  // With the API away it still takes a save, which waits in the queue, and shows what this
  // browser knows; a save the API refused comes back here to be fixed or dropped (ADR 0017).

  import { activeFragment, completeFragment, parseTags, suggest } from '@tagging';

  import type { SaveSheet } from '../shared/ipc';
  import { overlayApi } from './bridge';
  import { icons } from './icons';

  let { sheet }: { sheet: SaveSheet } = $props();

  const smart = overlayApi();
  // Seeded from the sheet once: Overlay rebuilds this component for every open, and after
  // that these change here (a tag removed, a save refused), not from the props.
  // svelte-ignore state_referenced_locally
  let bookmark = $state(sheet.bookmark);
  // svelte-ignore state_referenced_locally
  let error: string | null = $state(sheet.error);
  // svelte-ignore state_referenced_locally
  const pending = sheet.pending;
  const refused = pending?.refused === true;
  // A refused save's tags, to fix: they are the problem, so they are what you edit.
  let input = $state(refused ? pending!.tags.join(' ') : '');
  let busy = $state(false);
  let field: HTMLInputElement | undefined = $state();

  const site = $derived(hostOf(sheet.url));
  const current = $derived(bookmark?.tags ?? []);
  const known = $derived(sheet.offline ? (sheet.known ?? []) : []);
  const waiting = $derived(
    pending && !refused ? pending.tags.filter((t) => !current.includes(t) && !known.includes(t)) : [],
  );
  const typed = $derived(parseTags(input));
  const matches = $derived(
    suggest(sheet.vocabulary, activeFragment(input), { exclude: [...current, ...known, ...waiting, ...typed] }),
  );

  $effect(() => {
    field?.focus();
  });

  function hostOf(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url;
    }
  }

  function accept(name: string) {
    input = completeFragment(input, name);
    field?.focus();
  }

  async function save() {
    if (busy) return;
    busy = true;
    error = await smart.save(parseTags(input));
    busy = false; // on success the sheet has already closed
  }

  async function drop() {
    if (!pending) return;
    await smart.drop(pending.id);
    await smart.close();
  }

  async function remove(tag: string) {
    const result = await smart.removeTag(tag);
    if (typeof result === 'string') error = result;
    else bookmark = result;
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      void save();
    } else if (event.key === 'Tab' && !event.shiftKey && matches[0]) {
      event.preventDefault(); // Tab takes the top suggestion, as an omnibox would
      accept(matches[0].name);
    }
  }
</script>

<header>
  <div class="state" class:saved={bookmark || sheet.known} class:waiting={pending && !refused} class:refused>
    {#if refused}
      Refused
    {:else if pending}
      Waiting to save
    {:else if bookmark}
      {bookmark.tags.length ? 'Saved' : 'Saved · untagged'}
    {:else if sheet.offline && sheet.known}
      {sheet.known.length ? 'Saved' : 'Saved · untagged'}
    {:else if sheet.offline}
      Not known offline
    {:else}
      Not saved yet
    {/if}
  </div>
  <h1 title={sheet.url}>{sheet.title || sheet.url}</h1>
  <p class="site">{site}</p>
</header>

{#if sheet.offline}
  <p class="notice" role="status">Can’t reach your bookmarks API. This page will be saved when it’s back.</p>
{/if}
{#if refused}
  <p class="error" role="alert">
    Your bookmarks API refused this save: {pending!.lastError}. Fix the tags and save again, or drop it.
  </p>
{/if}

{#if known.length}
  <ul class="chips current" aria-label="Tags on this page">
    {#each known as tag (tag)}
      <li><span class="chip fixed" title="Tags can be removed once your bookmarks API is back">{tag}</span></li>
    {/each}
  </ul>
{/if}

{#if waiting.length}
  <ul class="chips current" aria-label="Tags waiting to be saved">
    {#each waiting as tag (tag)}
      <li><span class="chip fixed waiting" title="Waiting for your bookmarks API">{tag}</span></li>
    {/each}
  </ul>
{/if}

{#if current.length}
  <ul class="chips current" aria-label="Tags on this page">
    {#each current as tag (tag)}
      <li>
        <button class="chip" title={`Remove "${tag}"`} onclick={() => remove(tag)}>
          {tag}<span class="x" aria-hidden="true">{@html icons.close}</span>
        </button>
      </li>
    {/each}
  </ul>
{/if}

<input
  bind:this={field}
  bind:value={input}
  onkeydown={onKey}
  placeholder={current.length || known.length || waiting.length ? 'Add more tags' : 'Add tags, separated by spaces'}
  spellcheck="false"
  autocomplete="off"
  aria-label="Tags"
/>

{#if matches.length}
  <ul class="chips suggestions" aria-label="Suggestions">
    {#each matches as entry, i (entry.name)}
      <li>
        <button class="chip suggestion" class:top={i === 0} onclick={() => accept(entry.name)}>
          {entry.name}<span class="count">{entry.count}</span>
        </button>
      </li>
    {/each}
  </ul>
{/if}

{#if error}
  <p class="error" role="alert">{error}</p>
{/if}

<footer>
  <span class="hint">Enter to save · Tab takes a suggestion · Esc closes</span>
  <span class="buttons">
    {#if pending}
      <button class="secondary" onclick={drop} title="Give up on the save still waiting">Drop</button>
    {/if}
    <button class="primary" disabled={busy} onclick={save}>
      {refused ? 'Save again' : bookmark || known.length || pending ? 'Add tags' : 'Save'}
    </button>
  </span>
</footer>

<style>
  header {
    margin-bottom: 12px;
  }

  .state {
    display: inline-block;
    margin-bottom: 8px;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--chip);
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
  }

  .state.saved,
  .state.waiting {
    background: var(--accent-soft);
    color: var(--accent);
  }

  .state.refused {
    background: none;
    color: var(--danger);
    box-shadow: inset 0 0 0 1px currentColor;
  }

  .notice {
    margin: 0 0 12px;
    padding: 8px 10px;
    border-radius: 8px;
    background: var(--chip);
    color: var(--text-muted);
    font-size: 12px;
  }

  h1 {
    display: -webkit-box;
    margin: 0;
    overflow: hidden;
    font-size: 14px;
    font-weight: 600;
    line-height: 1.3;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
  }

  .site {
    margin: 2px 0 0;
    color: var(--text-muted);
    font-size: 12px;
  }

  input {
    width: 100%;
    height: 34px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--field-focus);
    outline: none;
  }

  input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 0 0 10px;
    padding: 0;
    list-style: none;
  }

  .suggestions {
    margin: 10px 0 0;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 24px;
    padding: 0 6px 0 9px;
    border: 1px solid var(--chip-border);
    border-radius: 12px;
    background: var(--chip);
    font-size: 12px;
  }

  .chip:hover:not(.fixed) {
    border-color: var(--text-muted);
  }

  .chip.fixed {
    padding-right: 9px;
  }

  .chip.waiting {
    border-style: dashed;
    border-color: var(--accent);
    background: none;
  }

  .x {
    display: grid;
    place-items: center;
    color: var(--text-muted);
  }

  .x :global(svg) {
    width: 11px;
    height: 11px;
  }

  .suggestion {
    padding-right: 8px;
  }

  .suggestion.top {
    border-color: var(--accent);
  }

  .count {
    color: var(--text-muted);
    font-size: 11px;
  }

  .error {
    margin: 10px 0 0;
    color: var(--danger);
    font-size: 12px;
  }

  footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-top: 14px;
  }

  .hint {
    color: var(--text-muted);
    font-size: 11px;
  }

  .buttons {
    display: flex;
    flex: none;
    gap: 8px;
  }

  .secondary {
    height: 30px;
    padding: 0 14px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
    font-weight: 600;
  }

  .primary {
    flex: none;
    height: 30px;
    padding: 0 16px;
    border: 0;
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    font-weight: 600;
  }

  .primary:disabled {
    opacity: 0.6;
  }
</style>
