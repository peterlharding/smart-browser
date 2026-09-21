<script lang="ts">
  // The overlay: a transparent view over the page, attached only while a card is open
  // (ADR 0015). Clicking outside the card or pressing Escape closes it.

  import type { OverlayState } from '../shared/ipc';
  import { overlayApi } from './bridge';
  import SaveSheet from './SaveSheet.svelte';
  import Settings from './Settings.svelte';

  const smart = overlayApi();
  let view: OverlayState | null = $state(null);
  let generation = $state(0); // a fresh card each time, so no state leaks between opens

  smart.onState((next) => {
    view = next;
    generation += 1;
  });

  function onKey(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault();
      void smart.close();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<!-- A click-catcher around the card; the keyboard's way out is Escape, above. -->
<div class="backdrop" role="presentation" onmousedown={(e) => e.target === e.currentTarget && smart.close()}>
  {#if view}
    {#key generation}
      <div class="card" class:settings={view.mode === 'settings'} role="dialog" aria-modal="true">
        {#if view.mode === 'save'}
          <SaveSheet sheet={view} />
        {:else}
          <Settings settings={view} />
        {/if}
      </div>
    {/key}
  {/if}
</div>

<style>
  :global(html),
  :global(body) {
    background: transparent;
  }

  .backdrop {
    position: fixed;
    inset: 0;
  }

  .card {
    position: absolute;
    top: 6px;
    right: 44px; /* under the toolbar's save button */
    width: 380px;
    max-height: calc(100% - 12px);
    overflow: auto;
    padding: 14px 16px 16px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
    box-shadow: var(--shadow);
    user-select: text;
    animation: appear 120ms ease-out;
  }

  .card.settings {
    right: 8px; /* under the settings button */
    width: 420px;
  }

  @keyframes appear {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
</style>
