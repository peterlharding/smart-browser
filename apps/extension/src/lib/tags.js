/**
 * Tag parsing. Pure functions, no browser APIs -- so `node --test` can exercise them.
 *
 * The rules here exist because of what the audit found in the existing corpus: 567 tags
 * with 32 near-duplicate pairs, four case/punctuation collisions, and one blank tag on 43
 * bookmarks. Most of that came from free-text entry with no normalisation at the point of
 * typing. This is the point of typing.
 */

/**
 * Split a free-text tag field into clean tag names.
 *
 * Accepts commas, spaces and newlines as separators. Lowercases, trims, and removes
 * duplicates while preserving the order typed.
 */
export function parseTags(input) {
  if (!input) return [];
  const seen = new Set();
  const out = [];
  for (const raw of String(input).split(/[,\n\r\t ]+/)) {
    const tag = raw.trim().toLowerCase();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    out.push(tag);
  }
  return out;
}

/**
 * The text a user is part-way through typing, for autocomplete.
 * Returns "" when the cursor sits just after a separator.
 */
export function activeFragment(input) {
  if (!input) return '';
  const parts = String(input).split(/[,\n\r\t ]+/);
  return parts[parts.length - 1].trim().toLowerCase();
}

/** Replace the fragment being typed with a chosen completion, leaving a trailing comma. */
export function completeFragment(input, choice) {
  const text = String(input ?? '');
  const match = text.match(/[^,\n\r\t ]*$/);
  const start = match ? match.index : text.length;
  return `${text.slice(0, start)}${choice}, `;
}

/**
 * Rank vocabulary entries against what has been typed.
 *
 * Prefix matches sort above substring matches, and within each group the more-used tag
 * wins -- with 567 tags, usage is what makes the list useful rather than alphabetical.
 */
export function suggest(vocabulary, fragment, { limit = 8, exclude = [] } = {}) {
  const skip = new Set(exclude);
  const frag = (fragment || '').toLowerCase();
  return vocabulary
    .filter((t) => t.name && !skip.has(t.name))
    .map((t) => {
      const name = t.name.toLowerCase();
      if (!frag) return { tag: t, rank: 2 };
      if (name.startsWith(frag)) return { tag: t, rank: 0 };
      if (name.includes(frag)) return { tag: t, rank: 1 };
      return null;
    })
    .filter(Boolean)
    .sort((a, b) => a.rank - b.rank || (b.tag.count ?? 0) - (a.tag.count ?? 0))
    .slice(0, limit)
    .map((entry) => entry.tag);
}
