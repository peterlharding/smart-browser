/** Extension settings, in chrome.storage.sync so they follow the profile. */

export const DEFAULTS = {
  baseUrl: 'http://127.0.0.1:8000',
  token: '',
};

export async function loadSettings(storage = chrome.storage.sync) {
  const stored = await storage.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

export async function saveSettings(values, storage = chrome.storage.sync) {
  await storage.set(values);
}
