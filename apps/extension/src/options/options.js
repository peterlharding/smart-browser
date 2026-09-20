import { BookmarksApi } from '../lib/api.js';
import { loadSettings, saveSettings } from '../lib/settings.js';

const el = {
  baseUrl: document.getElementById('baseUrl'),
  token: document.getElementById('token'),
  save: document.getElementById('save'),
  test: document.getElementById('test'),
  message: document.getElementById('message'),
};

const settings = await loadSettings();
el.baseUrl.value = settings.baseUrl;
el.token.value = settings.token;

el.save.addEventListener('click', async () => {
  await saveSettings({ baseUrl: el.baseUrl.value.trim(), token: el.token.value.trim() });
  show('Saved.');
});

el.test.addEventListener('click', async () => {
  const api = new BookmarksApi({
    baseUrl: el.baseUrl.value.trim(),
    token: el.token.value.trim(),
  });
  try {
    const health = await api.health();
    // Report the contract version, not just "ok": a server on a different contract is
    // reachable and healthy and still cannot talk to this extension.
    show(
      `Connected. API ${health.version}, contract v${health.contract}, ` +
        `schema ${health.schema_revision ?? 'unstamped'}.`,
    );
  } catch (error) {
    show(error.message, true);
  }
});

function show(text, isError = false) {
  el.message.textContent = text;
  el.message.className = `message${isError ? ' message--error' : ''}`;
  el.message.hidden = false;
}
