<script lang="ts">
  // The chrome: tab strip and toolbar, 80px across the top of the window (ADR 0015).
  // Everything it shows arrives as ChromeState from the main process; everything it does
  // is a request back. It keeps no state of its own but what the omnibox is being typed.

  import type { ChromeState, SavedState, TabState } from '../shared/ipc';
  import { chromeApi } from './bridge';
  import { icons } from './icons';

  const smart = chromeApi();
  const isMac = navigator.userAgent.includes('Mac OS X');

  let chrome: ChromeState = $state({
    tabs: [],
    activeId: null,
    canGoBack: false,
    canGoForward: false,
    saved: { kind: 'not-web' },
    focusOmnibox: 0,
  });
  let typed = $state('');
  let editing = $state(false);
  let omnibox: HTMLInputElement | undefined = $state();
  let dragging: number | null = $state(null);

  const active = $derived(chrome.tabs.find((t) => t.id === chrome.activeId));
  const shownUrl = $derived(active && active.url !== 'about:blank' ? active.url : '');

  smart.onBlur(() => omnibox?.blur());

  let lastFocus = 0;
  smart.onState((next) => {
    // Another tab is another page: whatever was being typed was about the last one.
    if (next.activeId !== chrome.activeId && editing) {
      editing = false;
      omnibox?.blur();
    }
    chrome = next;
    if (next.focusOmnibox !== lastFocus) {
      lastFocus = next.focusOmnibox;
      queueMicrotask(focusOmnibox);
    }
  });

  function focusOmnibox() {
    if (!omnibox) return;
    omnibox.focus();
    omnibox.select();
  }

  function startEditing() {
    typed = shownUrl;
    editing = true;
    queueMicrotask(() => omnibox?.select());
  }

  function onOmniboxKey(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      const input = typed.trim();
      if (!input) return;
      editing = false;
      omnibox?.blur();
      void smart.navigate(input);
    } else if (event.key === 'Escape') {
      typed = shownUrl;
      editing = false;
      omnibox?.blur();
    }
  }

  function savedLabel(saved: SavedState): string {
    switch (saved.kind) {
      case 'saved':
        return saved.tags.length ? `Saved with ${saved.tags.join(', ')} (⌘⇧B)` : 'Saved, untagged (⌘⇧B)';
      case 'savable':
        return 'Save this page with tags (⌘⇧B)';
      case 'unconfigured':
        return 'Connect to your bookmarks API in Settings';
      case 'unavailable':
        return saved.reason;
      case 'not-web':
        return 'Only web pages can be saved';
    }
  }

  function tabTitle(tab: TabState): string {
    return tab.title || (tab.url === 'about:blank' ? 'New Tab' : tab.url);
  }

  function onTabMouseDown(event: MouseEvent, tab: TabState) {
    if (event.button === 1) {
      event.preventDefault(); // middle click closes, as everywhere else
      void smart.closeTab(tab.id);
    } else if (event.button === 0) {
      void smart.activateTab(tab.id);
    }
  }

  function onDrop(event: DragEvent, index: number) {
    event.preventDefault();
    if (dragging !== null) void smart.moveTab(dragging, index);
    dragging = null;
  }
</script>

<div class="chrome" class:mac={isMac}>
  <div class="strip" role="tablist" aria-label="Tabs">
    {#each chrome.tabs as tab, index (tab.id)}
      <div
        class="tab"
        class:active={tab.id === chrome.activeId}
        class:dragging={dragging === tab.id}
        role="tab"
        tabindex="-1"
        aria-selected={tab.id === chrome.activeId}
        title={tabTitle(tab)}
        draggable="true"
        onmousedown={(e) => onTabMouseDown(e, tab)}
        ondragstart={() => (dragging = tab.id)}
        ondragend={() => (dragging = null)}
        ondragover={(e) => e.preventDefault()}
        ondrop={(e) => onDrop(e, index)}
      >
        <span class="favicon">
          {#if tab.loading}
            <span class="spinner" aria-label="Loading"></span>
          {:else if tab.favicon}
            <img src={tab.favicon} alt="" width="16" height="16" />
          {:else}
            {@html icons.globe}
          {/if}
        </span>
        <span class="title">{tabTitle(tab)}</span>
        <button
          class="close"
          title="Close tab (⌘W)"
          aria-label="Close tab"
          onmousedown={(e) => e.stopPropagation()}
          onclick={() => smart.closeTab(tab.id)}
        >
          {@html icons.close}
        </button>
      </div>
    {/each}
    <button class="new-tab" title="New tab (⌘T)" aria-label="New tab" onclick={() => smart.newTab()}>
      {@html icons.plus}
    </button>
    <div class="drag-space"></div>
  </div>

  <div class="toolbar">
    <button class="icon" title="Back (⌘[)" aria-label="Back" disabled={!chrome.canGoBack} onclick={() => smart.back()}>
      {@html icons.back}
    </button>
    <button
      class="icon"
      title="Forward (⌘])"
      aria-label="Forward"
      disabled={!chrome.canGoForward}
      onclick={() => smart.forward()}
    >
      {@html icons.forward}
    </button>
    {#if active?.loading}
      <button class="icon" title="Stop" aria-label="Stop" onclick={() => smart.stop()}>{@html icons.stop}</button>
    {:else}
      <button class="icon" title="Reload (⌘R)" aria-label="Reload" onclick={() => smart.reload()}>
        {@html icons.reload}
      </button>
    {/if}

    <input
      class="omnibox"
      bind:this={omnibox}
      value={editing ? typed : shownUrl}
      oninput={(e) => (typed = e.currentTarget.value)}
      onfocus={startEditing}
      onblur={() => (editing = false)}
      onkeydown={onOmniboxKey}
      placeholder="Search or enter address"
      spellcheck="false"
      autocomplete="off"
      aria-label="Address and search bar"
    />

    <button
      class="icon save"
      class:saved={chrome.saved.kind === 'saved'}
      class:problem={chrome.saved.kind === 'unavailable'}
      title={savedLabel(chrome.saved)}
      aria-label={savedLabel(chrome.saved)}
      disabled={chrome.saved.kind === 'not-web'}
      onclick={() => (chrome.saved.kind === 'unconfigured' ? smart.openSettings() : smart.openSaveSheet())}
    >
      {#if chrome.saved.kind === 'saved'}
        {@html icons.bookmarkFilled}
        {#if chrome.saved.tags.length}<span class="count">{chrome.saved.tags.length}</span>{/if}
      {:else if chrome.saved.kind === 'unavailable'}
        {@html icons.warning}
      {:else}
        {@html icons.bookmark}
      {/if}
    </button>
    <button class="icon" title="Settings (⌘,)" aria-label="Settings" onclick={() => smart.openSettings()}>
      {@html icons.settings}
    </button>
  </div>
</div>

<style>
  .chrome {
    display: flex;
    flex-direction: column;
    height: 80px;
    background: var(--strip);
  }

  /* --- tab strip: 38px, draggable except where there is something to click --- */

  .strip {
    display: flex;
    align-items: flex-end;
    height: 38px;
    padding: 0 8px;
    gap: 1px;
    -webkit-app-region: drag;
  }

  .mac .strip {
    padding-left: 78px; /* the traffic lights */
  }

  .tab {
    position: relative;
    display: flex;
    align-items: center;
    gap: 7px;
    flex: 0 1 220px;
    min-width: 44px;
    height: 32px;
    padding: 0 6px 0 10px;
    border-radius: 8px 8px 0 0;
    color: var(--text-muted);
    -webkit-app-region: no-drag;
  }

  .tab:not(.active):hover {
    background: var(--strip-hover);
  }

  .tab.active {
    background: var(--toolbar);
    color: var(--text);
  }

  .tab.dragging {
    opacity: 0.5;
  }

  /* A hairline between inactive neighbours, as Chrome draws it. */
  .tab:not(.active) + .tab:not(.active)::before {
    content: '';
    position: absolute;
    left: -1px;
    top: 9px;
    bottom: 9px;
    width: 1px;
    background: var(--border);
  }

  .favicon {
    display: grid;
    place-items: center;
    flex: none;
    width: 16px;
    height: 16px;
  }

  .favicon img {
    display: block;
    width: 16px;
    height: 16px;
  }

  .spinner {
    width: 13px;
    height: 13px;
    border: 2px solid var(--accent-soft);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 12px;
  }

  .close {
    display: grid;
    place-items: center;
    flex: none;
    width: 18px;
    height: 18px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: none;
    color: var(--text-muted);
    opacity: 0;
  }

  .close :global(svg) {
    width: 12px;
    height: 12px;
  }

  .tab:hover .close,
  .tab.active .close {
    opacity: 1;
  }

  .close:hover {
    background: var(--hover);
    color: var(--text);
  }

  .new-tab {
    display: grid;
    place-items: center;
    flex: none;
    width: 28px;
    height: 28px;
    margin: 0 0 2px 4px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: none;
    color: var(--text-muted);
    -webkit-app-region: no-drag;
  }

  .new-tab:hover {
    background: var(--hover);
    color: var(--text);
  }

  .drag-space {
    flex: 1;
    align-self: stretch;
  }

  /* --- toolbar: 42px --- */

  .toolbar {
    display: flex;
    align-items: center;
    gap: 2px;
    height: 42px;
    padding: 0 8px;
    background: var(--toolbar);
    border-bottom: 1px solid var(--border);
  }

  .icon {
    position: relative;
    display: grid;
    place-items: center;
    flex: none;
    width: 30px;
    height: 30px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: none;
    color: var(--text-muted);
  }

  .icon:hover:not(:disabled) {
    background: var(--hover);
    color: var(--text);
  }

  .icon:disabled {
    opacity: 0.35;
  }

  .omnibox {
    flex: 1;
    min-width: 0;
    height: 30px;
    margin: 0 6px;
    padding: 0 14px;
    border: 1px solid transparent;
    border-radius: 15px;
    background: var(--field);
    outline: none;
    user-select: text;
  }

  .omnibox:hover {
    border-color: var(--border);
  }

  .omnibox:focus {
    background: var(--field-focus);
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .save.saved {
    color: var(--saved);
  }

  .save.problem {
    color: var(--warn);
  }

  .count {
    position: absolute;
    right: 1px;
    bottom: 2px;
    min-width: 13px;
    height: 13px;
    padding: 0 3px;
    border-radius: 7px;
    background: var(--saved);
    color: var(--toolbar);
    font-size: 9px;
    font-weight: 700;
    line-height: 13px;
    text-align: center;
  }
</style>
