/**
 * Types for tags.js, for the Smart-Browser shell, which imports it rather than copying it
 * (ADR 0015). The extension has no build step and ignores this file.
 */

export interface VocabularyEntry {
  name: string;
  count?: number | null;
}

export function parseTags(input: string | null | undefined): string[];
export function activeFragment(input: string | null | undefined): string;
export function completeFragment(input: string | null | undefined, choice: string): string;
export function suggest<T extends VocabularyEntry>(
  vocabulary: T[],
  fragment: string | null | undefined,
  options?: { limit?: number; exclude?: string[] },
): T[];
