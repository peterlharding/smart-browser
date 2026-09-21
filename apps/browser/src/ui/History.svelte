<script lang="ts">
  // The history page, smart://history/ (ADR 0016), laid out as Chrome's: a search box, a
  // card per day, a row per page with its time, favicon, title and site, a menu on each
  // row, ticking rows to delete them, and Delete browsing data at the side.
  //
  // What it shows is in its address (?q=, ?host=, ?day=), so a restored tab shows it again.

  import { SvelteSet } from 'svelte/reactivity';

  import type { ClearRange, HistoryEntry, HistoryView } from '../shared/ipc';
  import { historyApi } from './bridge';
  import { icons } from './icons';

  const smart = historyApi();
  const PAGE = 100;
  const RANGES: { value: ClearRange; label: string }[] = [
    { value: 'hour', label: 'Last hour' },
    { value: 'day', label: 'Last 24 hours' },
    { value: 'week', label: 'Last 7 days' },
    { value: 'month', label: 'Last 4 weeks' },
    { value: 'all', label: 'All time' },
  ];

  const initial = new URLSearchParams(location.search);
  let text = $state(initial.get('q') ?? '');
  let typed = $state(initial.get('q') ?? '');
  let host = $state(initial.get('host') ?? '');
  let day = $state(initial.get('day') ?? '');

  let entries: HistoryEntry[] = $state([]);
  let more = $state(false);
  let loaded = $state(false);
  let loadingMore = $state(false);
  let nearEnd = $state(false);

  const selected = new SvelteSet<string>();
  let anchor: number | null = null; // the row a shift-click selects from
  let menu: { entry: HistoryEntry; x: number; y: number } | null = $state(null);
  let dialog: 'clear' | 'remove' | null = $state(initial.get('panel') === 'clear' ? 'clear' : null);
  let clearing = $state(false);
  let range: ClearRange = $state('hour');
  let clearHistory = $state(true);
  let clearCookies = $state(false);
  let clearCache = $state(false);

  let search: HTMLInputElement | undefined = $state();
  let scroller: HTMLElement | undefined = $state();
  let sentinel: HTMLElement | undefined = $state();
  let dialogFirst: HTMLElement | undefined = $state();
  let focusSearch = $state(1); // the page opens ready to search, as Chrome's does

  const key = (e: HistoryEntry) => `${e.pageId}|${e.day}`;
  const filtered = $derived(Boolean(text || host || day));

  const groups = $derived.by(() => {
    const out: { day: string; entries: HistoryEntry[] }[] = [];
    for (const entry of entries) {
      const last = out.at(-1);
      if (last?.day === entry.day) last.entries.push(entry);
      else out.push({ day: entry.day, entries: [entry] });
    }
    return out;
  });

  // --- loading -----------------------------------------------------------------------

  let generation = 0; // moved on by every fresh load, so a slower, older answer is dropped

  async function reload(keep = false) {
    const mine = ++generation;
    const limit = keep ? Math.max(PAGE, entries.length) : PAGE;
    const result = await smart.query({ text, host, day, limit });
    if (mine !== generation) return;
    entries = result.entries;
    more = result.more;
    loaded = true;
    const present = new Set(entries.map(key));
    for (const k of selected) if (!present.has(k)) selected.delete(k);
    if (!keep) scroller?.scrollTo({ top: 0 });
  }

  async function loadMore() {
    const last = entries.at(-1);
    if (!more || loadingMore || !last) return;
    const mine = generation;
    loadingMore = true;
    const result = await smart.query({ text, host, day, before: last.at, limit: PAGE });
    loadingMore = false;
    if (mine !== generation) return;
    entries = [...entries, ...result.entries];
    more = result.more;
  }

  // What is shown follows the filters, and the address follows them too.
  $effect(() => {
    const params = new URLSearchParams();
    if (text) params.set('q', text);
    if (host) params.set('host', host);
    if (day) params.set('day', day);
    const query = params.toString();
    window.history.replaceState(null, '', query ? `?${query}` : location.pathname);
    void reload();
  });

  // Rows load as the end of the list comes near.
  $effect(() => {
    if (!sentinel || !scroller) return;
    const observer = new IntersectionObserver((seen) => (nearEnd = seen.some((s) => s.isIntersecting)), {
      root: scroller,
      rootMargin: '600px',
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  });

  $effect(() => {
    if (nearEnd && more && !loadingMore) void loadMore();
  });

  $effect(() => {
    if (focusSearch && search && !dialog) {
      search.focus();
      search.select();
    }
  });

  $effect(() => {
    if (dialog) dialogFirst?.focus();
  });

  smart.onChanged(() => void reload(true));

  smart.onView((view: HistoryView) => {
    typed = text = view.text ?? '';
    host = view.host ?? '';
    day = view.day ?? '';
    selected.clear();
    menu = null;
    dialog = view.panel === 'clear' ? 'clear' : null;
    focusSearch += 1;
  });

  // --- searching ---------------------------------------------------------------------

  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => (text = typed.trim()), 150);
  }

  function onSearchKey(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      clearTimeout(searchTimer);
      text = typed.trim();
    } else if (event.key === 'Escape' && typed) {
      event.stopPropagation();
      clearSearch();
    }
  }

  function clearSearch() {
    clearTimeout(searchTimer);
    typed = text = '';
    search?.focus();
  }

  // --- rows --------------------------------------------------------------------------

  function open(event: MouseEvent, entry: HistoryEntry) {
    event.preventDefault();
    const newTab = event.metaKey || event.ctrlKey || event.button === 1;
    void smart.open(entry.url, newTab ? (event.shiftKey ? 'foreground' : 'background') : 'current');
  }

  function toggle(event: MouseEvent, entry: HistoryEntry) {
    const index = entries.indexOf(entry);
    const on = !selected.has(key(entry));
    if (event.shiftKey && anchor !== null) {
      const [from, to] = [Math.min(anchor, index), Math.max(anchor, index)];
      for (const e of entries.slice(from, to + 1)) {
        if (on) selected.add(key(e));
        else selected.delete(key(e));
      }
    } else if (on) {
      selected.add(key(entry));
    } else {
      selected.delete(key(entry));
    }
    anchor = index;
  }

  function openMenu(event: MouseEvent, entry: HistoryEntry) {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    menu = menu?.entry === entry ? null : { entry, x: rect.right, y: rect.bottom + 4 };
  }

  function moreFromSite(entry: HistoryEntry) {
    menu = null;
    typed = text = '';
    day = '';
    host = entry.host;
  }

  async function remove(items: HistoryEntry[]) {
    menu = null;
    const gone = new Set(items.map(key));
    entries = entries.filter((e) => !gone.has(key(e)));
    for (const k of gone) selected.delete(k);
    await smart.remove(items.map(({ pageId, day }) => ({ pageId, day })));
  }

  async function removeSelected() {
    dialog = null;
    await remove(entries.filter((e) => selected.has(key(e))));
  }

  async function clearData() {
    clearing = true;
    await smart.clear({ range, history: clearHistory, cookies: clearCookies, cache: clearCache });
    clearing = false;
    dialog = null;
    focusSearch += 1;
  }

  function closeDialog() {
    dialog = null;
    focusSearch += 1;
  }

  function onKey(event: KeyboardEvent) {
    if (event.key !== 'Escape') return;
    if (menu) menu = null;
    else if (dialog) closeDialog();
    else if (selected.size) selected.clear();
  }

  // --- formatting --------------------------------------------------------------------

  const dayFormat = new Intl.DateTimeFormat(undefined, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
  const shortDayFormat = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  const timeFormat = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });

  function localDay(date: Date): string {
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function dateOf(d: string): Date {
    const [year, month, date] = d.split('-').map(Number);
    return new Date(year!, month! - 1, date!);
  }

  function heading(d: string): string {
    const full = dayFormat.format(dateOf(d));
    const now = new Date();
    if (d === localDay(now)) return `Today - ${full}`;
    now.setDate(now.getDate() - 1);
    if (d === localDay(now)) return `Yesterday - ${full}`;
    return full;
  }

  const site = (h: string) => h.replace(/^www\./, '');
  const label = (e: HistoryEntry) => e.title || e.url;
</script>

<svelte:window onkeydown={onKey} onmousedown={() => (menu = null)} />

<div class="page">
  <header class:selecting={selected.size > 0}>
    {#if selected.size}
      <div class="brand">
        <button class="icon inverse" aria-label="Clear selection" title="Clear selection" onclick={() => selected.clear()}>
          {@html icons.close}
        </button>
        <span class="count">{selected.size} selected</span>
      </div>
      <div class="actions">
        <button class="text inverse" onclick={() => selected.clear()}>Cancel</button>
        <button class="solid inverse" onclick={() => (dialog = 'remove')}>Delete</button>
      </div>
    {:else}
      <div class="brand"><span class="logo">{@html icons.clock}</span><h1>History</h1></div>
      <div class="search">
        <span class="glass">{@html icons.search}</span>
        <input
          bind:this={search}
          bind:value={typed}
          oninput={onSearchInput}
          onkeydown={onSearchKey}
          type="search"
          placeholder="Search history"
          aria-label="Search history"
          spellcheck="false"
          autocomplete="off"
        />
        {#if typed}
          <button class="icon clear" aria-label="Clear search" title="Clear search" onclick={clearSearch}>
            {@html icons.close}
          </button>
        {/if}
      </div>
      <button class="icon narrow-only" aria-label="Delete browsing data" title="Delete browsing data" onclick={() => (dialog = 'clear')}>
        {@html icons.trash}
      </button>
    {/if}
  </header>

  <div class="body">
    <nav aria-label="History">
      <button class="nav-item current" aria-current="page" onclick={() => { typed = text = ''; host = ''; day = ''; }}>
        {@html icons.clock}<span>Browsing history</span>
      </button>
      <button class="nav-item" onclick={() => (dialog = 'clear')}>
        {@html icons.trash}<span>Delete browsing data</span>
      </button>
    </nav>

    <main bind:this={scroller}>
      <div class="column">
        {#if host || day}
          <div class="filters" aria-label="Showing">
            {#if host}
              <span class="filter">
                {site(host)}
                <button aria-label="Show all sites" title="Show all sites" onclick={() => (host = '')}>{@html icons.close}</button>
              </span>
            {/if}
            {#if day}
              <span class="filter">
                {shortDayFormat.format(dateOf(day))}
                <button aria-label="Show all days" title="Show all days" onclick={() => (day = '')}>{@html icons.close}</button>
              </span>
            {/if}
          </div>
        {/if}

        {#if loaded && !entries.length}
          <div class="empty">
            <span class="empty-icon">{@html filtered ? icons.search : icons.clock}</span>
            <p>{filtered ? 'No history matches' : 'Pages you visit appear here'}</p>
          </div>
        {/if}

        {#each groups as group (group.day)}
          <section class="card" aria-label={heading(group.day)}>
            <h2>{heading(group.day)}</h2>
            <ul>
              {#each group.entries as entry (key(entry))}
                <li class="row" class:selected={selected.has(key(entry))}>
                  <input
                    type="checkbox"
                    aria-label={`Select ${label(entry)}`}
                    checked={selected.has(key(entry))}
                    onclick={(e) => toggle(e, entry)}
                  />
                  <span class="time">{timeFormat.format(entry.at)}</span>
                  <span class="favicon">
                    {#if entry.favicon}<img src={entry.favicon} alt="" width="16" height="16" />{:else}{@html icons.globe}{/if}
                  </span>
                  <a
                    class="title"
                    href={entry.url}
                    title={entry.url}
                    onclick={(e) => open(e, entry)}
                    onauxclick={(e) => e.button === 1 && open(e, entry)}
                    onmousedown={(e) => e.button === 1 && e.preventDefault()}>{label(entry)}</a
                  >
                  <span class="host">{site(entry.host)}</span>
                  <button
                    class="icon more"
                    class:open={menu?.entry === entry}
                    aria-label={`Actions for ${label(entry)}`}
                    aria-haspopup="menu"
                    onmousedown={(e) => e.stopPropagation()}
                    onclick={(e) => openMenu(e, entry)}
                  >
                    {@html icons.more}
                  </button>
                </li>
              {/each}
            </ul>
          </section>
        {/each}
        <div class="sentinel" bind:this={sentinel}></div>
      </div>
    </main>
  </div>
</div>

{#if menu}
  <div
    class="menu"
    role="menu"
    tabindex="-1"
    style:top={`${menu.y}px`}
    style:right={`${window.innerWidth - menu.x}px`}
    onmousedown={(e) => e.stopPropagation()}
  >
    <button role="menuitem" disabled={!menu.entry.host} onclick={() => moreFromSite(menu!.entry)}>More from this site</button>
    <button role="menuitem" onclick={() => remove([menu!.entry])}>Delete from history</button>
  </div>
{/if}

{#if dialog}
  <div class="scrim" role="presentation" onmousedown={(e) => e.target === e.currentTarget && closeDialog()}>
    {#if dialog === 'remove'}
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="remove-title">
        <h2 id="remove-title">Delete selected items?</h2>
        <p>
          {selected.size === 1 ? 'This page' : `These ${selected.size} pages`} will be deleted from your
          history on the days shown.
        </p>
        <footer>
          <button class="secondary" onclick={closeDialog}>Cancel</button>
          <button class="primary" bind:this={dialogFirst} onclick={removeSelected}>Delete</button>
        </footer>
      </div>
    {:else}
      <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="clear-title">
        <h2 id="clear-title">Delete browsing data</h2>
        <label class="range">
          <span>Time range</span>
          <select bind:this={dialogFirst} bind:value={range}>
            {#each RANGES as option (option.value)}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
        </label>
        <label class="kind">
          <input type="checkbox" bind:checked={clearHistory} />
          <span><strong>Browsing history</strong><small>Pages you visited, and tabs you closed</small></span>
        </label>
        <label class="kind">
          <input type="checkbox" bind:checked={clearCookies} />
          <span><strong>Cookies and other site data</strong><small>Signs you out of most sites</small></span>
        </label>
        <label class="kind">
          <input type="checkbox" bind:checked={clearCache} />
          <span><strong>Cached images and files</strong><small>Some sites may load more slowly on your next visit</small></span>
        </label>
        {#if range !== 'all' && (clearCookies || clearCache)}
          <p class="note">Cookies and cached files are deleted for all time, not only the range above.</p>
        {/if}
        <footer>
          <button class="secondary" onclick={closeDialog}>Cancel</button>
          <button
            class="primary"
            disabled={clearing || !(clearHistory || clearCookies || clearCache)}
            onclick={clearData}>Delete data</button
          >
        </footer>
      </div>
    {/if}
  </div>
{/if}

<style>
  :global(body) {
    background: var(--page);
  }

  .page {
    display: grid;
    grid-template-rows: 56px 1fr;
    height: 100%;
  }

  /* --- header: the title and search, or what is selected --- */

  header {
    display: grid;
    grid-template-columns: 232px 1fr auto;
    align-items: center;
    padding: 0 16px 0 20px;
    background: var(--toolbar);
    border-bottom: 1px solid var(--border);
  }

  header.selecting {
    grid-template-columns: 1fr auto;
    background: var(--accent);
    border-bottom-color: var(--accent);
    color: #fff;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .logo {
    display: grid;
    color: var(--accent);
  }

  .logo :global(svg) {
    width: 22px;
    height: 22px;
  }

  h1 {
    margin: 0;
    font-size: 18px;
    font-weight: 500;
  }

  .count {
    font-size: 15px;
    font-weight: 500;
  }

  .actions {
    display: flex;
    gap: 8px;
  }

  .search {
    position: relative;
    justify-self: center;
    width: min(680px, 100%);
  }

  .search input {
    width: 100%;
    height: 38px;
    padding: 0 40px;
    border: 1px solid transparent;
    border-radius: 19px;
    background: var(--field);
    outline: none;
    user-select: text;
  }

  .search input::-webkit-search-cancel-button {
    display: none;
  }

  .search input:focus {
    background: var(--field-focus);
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .glass {
    position: absolute;
    top: 11px;
    left: 14px;
    display: grid;
    color: var(--text-muted);
    pointer-events: none;
  }

  .search .clear {
    position: absolute;
    top: 4px;
    right: 5px;
  }

  /* --- buttons --- */

  .icon {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: none;
    color: var(--text-muted);
  }

  .icon:hover {
    background: var(--hover);
    color: var(--text);
  }

  .inverse,
  .inverse:hover {
    color: #fff;
  }

  .icon.inverse:hover,
  .text.inverse:hover {
    background: rgb(255 255 255 / 16%);
  }

  .text,
  .solid,
  .primary,
  .secondary {
    height: 30px;
    padding: 0 16px;
    border-radius: 8px;
    font-weight: 600;
  }

  .text {
    border: 0;
    background: none;
  }

  .solid {
    border: 0;
    background: #fff;
    color: var(--accent);
  }

  .primary {
    border: 0;
    background: var(--accent);
    color: #fff;
  }

  .primary:disabled {
    opacity: 0.5;
  }

  .secondary {
    border: 1px solid var(--border);
    background: var(--card);
  }

  .narrow-only {
    display: none;
  }

  /* --- the side and the list --- */

  .body {
    display: grid;
    grid-template-columns: 232px 1fr;
    min-height: 0;
  }

  nav {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 12px 12px 12px 8px;
  }

  .nav-item {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 36px;
    padding: 0 12px;
    border: 0;
    border-radius: 0 18px 18px 0;
    background: none;
    color: var(--text);
    text-align: left;
  }

  .nav-item:hover {
    background: var(--hover);
  }

  .nav-item.current {
    background: var(--accent-soft);
    color: var(--accent);
    font-weight: 600;
  }

  .nav-item :global(svg) {
    flex: none;
  }

  main {
    overflow-y: auto;
    padding: 16px 24px 32px;
  }

  .column {
    max-width: 960px;
    margin: 0 auto;
  }

  .filters {
    display: flex;
    gap: 8px;
    margin: 0 0 12px;
  }

  .filter {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 28px;
    padding: 0 4px 0 12px;
    border: 1px solid var(--chip-border);
    border-radius: 14px;
    background: var(--chip);
    font-weight: 500;
  }

  .filter button {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: none;
    color: var(--text-muted);
  }

  .filter button:hover {
    background: var(--hover);
    color: var(--text);
  }

  .filter :global(svg) {
    width: 12px;
    height: 12px;
  }

  .card {
    margin: 0 0 16px;
    padding: 4px 0 8px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--card);
  }

  .card h2 {
    margin: 0;
    padding: 14px 20px 8px;
    font-size: 13px;
    font-weight: 600;
  }

  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 40px;
    padding: 0 8px 0 20px;
  }

  .row:hover {
    background: var(--hover);
  }

  .row.selected {
    background: var(--selected);
  }

  .row input {
    flex: none;
    width: 16px;
    height: 16px;
    margin: 0;
    accent-color: var(--accent);
  }

  .time {
    flex: none;
    width: 64px;
    color: var(--text-muted);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
  }

  .favicon {
    display: grid;
    place-items: center;
    flex: none;
    width: 16px;
    height: 16px;
    color: var(--text-muted);
  }

  .favicon img {
    display: block;
    width: 16px;
    height: 16px;
  }

  .title {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    color: var(--text);
    text-decoration: none;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .title:hover {
    text-decoration: underline;
  }

  .host {
    flex: 1 1 0;
    min-width: 0;
    overflow: hidden;
    color: var(--text-muted);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .more {
    flex: none;
  }

  .more.open {
    background: var(--hover);
    color: var(--text);
  }

  .sentinel {
    height: 1px;
  }

  .empty {
    display: grid;
    justify-items: center;
    gap: 12px;
    padding: 96px 0;
    color: var(--text-muted);
  }

  .empty-icon :global(svg) {
    width: 48px;
    height: 48px;
    stroke-width: 1;
  }

  .empty p {
    margin: 0;
    font-size: 15px;
  }

  /* --- the row menu and dialogs --- */

  .menu {
    position: fixed;
    z-index: 2;
    display: grid;
    min-width: 200px;
    padding: 6px 0;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--card);
    box-shadow: var(--shadow);
  }

  .menu button {
    height: 32px;
    padding: 0 16px;
    border: 0;
    background: none;
    text-align: left;
  }

  .menu button:hover:not(:disabled) {
    background: var(--hover);
  }

  .menu button:disabled {
    color: var(--text-muted);
  }

  .scrim {
    position: fixed;
    inset: 0;
    z-index: 3;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 32%);
  }

  .dialog {
    width: min(440px, calc(100% - 32px));
    padding: 20px 24px;
    border-radius: 12px;
    background: var(--card);
    box-shadow: var(--shadow);
  }

  .dialog h2 {
    margin: 0 0 16px;
    font-size: 16px;
    font-weight: 600;
  }

  .dialog p {
    margin: 0 0 8px;
    color: var(--text-muted);
  }

  .range {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 0 0 12px;
  }

  .range select {
    height: 30px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--field);
  }

  .kind {
    display: flex;
    gap: 12px;
    padding: 8px 0;
  }

  .kind input {
    flex: none;
    width: 16px;
    height: 16px;
    margin: 2px 0 0;
    accent-color: var(--accent);
  }

  .kind span {
    display: grid;
    gap: 2px;
  }

  .kind strong {
    font-weight: 500;
  }

  .kind small {
    color: var(--text-muted);
    font-size: 12px;
  }

  .note {
    font-size: 12px;
  }

  .dialog footer {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 16px;
  }

  /* --- narrow windows: the side goes, and its one action moves to the header --- */

  @media (width < 760px) {
    header {
      grid-template-columns: auto 1fr auto;
      gap: 16px;
    }

    header.selecting {
      grid-template-columns: 1fr auto;
    }

    .body {
      grid-template-columns: 1fr;
    }

    nav {
      display: none;
    }

    .narrow-only {
      display: grid;
    }
  }
</style>
