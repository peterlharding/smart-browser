// Loaded with `-r` after Playwright's own Electron loader, which appends Chromium's test
// defaults with app.commandLine.appendSwitch, among them --password-store=basic. On Linux
// "basic" is no encryption at all, so the browser refuses to keep a token, as it should.
// CI provides GNOME Keyring; this points Chromium back at it. The last appendSwitch wins.
//
// (On macOS the same defaults give Chromium's mock keychain, which is what tests want:
// they never touch the real Keychain.)
const { app } = require('electron');

app.commandLine.appendSwitch('password-store', 'gnome-libsecret');
