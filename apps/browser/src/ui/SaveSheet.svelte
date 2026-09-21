<script lang="ts">
  // The save sheet, ⌘⇧B: whether this page is saved and with which tags, autocomplete from
  // your own vocabulary ranked by use, and one keystroke to save. The tag rules are the
  // extension's own code, imported (ADR 0015).

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
  let input = $state('');
  let busy = $state(false);
  let field: HTMLInputElement | undefined = $state();

  const site = $derived(hostOf(sheet.url));
  const current = $derived(bookmark?.tags ?? []);
  const typed = $derived(parseTags(input));
  const matches = $derived(
    suggest(sheet.vocabulary, activeFragment(input), { exclude: [...current, ...typed] }),
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
  <div class="state" class:saved={bookmark}>
    {#if bookmark}
      {bookmark.tags.length ? 'Saved' : 'Saved · untagged'}
    {:else}
      Not saved yet
    {/if}
  </div>
  <h1 title={sheet.url}>{sheet.title || sheet.url}</h1>
  <p class="site">{site}</p>
</header>

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
  placeholder={current.length ? 'Add more tags' : 'Add tags, separated by spaces'}
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
  <button class="primary" disabled={busy} onclick={save}>{bookmark ? 'Add tags' : 'Save'}</button>
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

  .state.saved {
    background: var(--accent-soft);
    color: var(--accent);
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

  .chip:hover {
    border-color: var(--text-muted);
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
