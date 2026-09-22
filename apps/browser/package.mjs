// Package the browser as Smart-Browser.app (ADR 0018), from what build.mjs put in out/.
// Electron's own pieces, one step each, rather than an all-in-one tool.
//
//   node package.mjs            dist/…/Smart-Browser.app, signed ad hoc: to try, and to test
//   node package.mjs --release  signed with Developer ID, notarized and stapled, with the
//                               DMG to install from and the zip updates come from
//
// A release signs on this Mac, with the Developer ID key in its Keychain, and notarizes
// with credentials stored once by `xcrun notarytool store-credentials` (see RELEASING.md).

import { notarize } from '@electron/notarize';
import { sign } from '@electron/osx-sign';
import { packager } from '@electron/packager';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const pkg = JSON.parse(readFileSync(join(here, 'package.json'), 'utf8'));
const release = process.argv.includes('--release');

const NAME = 'Smart-Browser';
const BUNDLE_ID = 'com.performiq.smart-browser';
const ARCH = 'arm64';
const DIST = join(here, 'dist');
const ENTITLEMENTS = join(here, 'assets', 'entitlements.plist');
// Overridable, so a different certificate or stored profile needs no edit here.
const IDENTITY = process.env.SMART_BROWSER_SIGNING_IDENTITY ?? 'Developer ID Application: Peter Harding (T5RDMAD9Q4)';
const NOTARY_PROFILE = process.env.SMART_BROWSER_NOTARY_PROFILE ?? 'smart-browser-notary';

const run = (command, args, options = {}) => execFileSync(command, args, { stdio: 'inherit', ...options });
const say = (message) => console.log(`\n== ${message}`);

if (!existsSync(join(here, 'out', 'main', 'index.cjs'))) {
  throw new Error('Nothing to package: out/ is empty. Build first (make browser-package builds).');
}
if (release) {
  // Both are checked before anything slow starts, and each says how to put it right.
  const identities = execFileSync('security', ['find-identity', '-v', '-p', 'codesigning'], { encoding: 'utf8' });
  if (!identities.includes(IDENTITY)) {
    throw new Error(`No signing identity "${IDENTITY}" in the Keychain (set SMART_BROWSER_SIGNING_IDENTITY).`);
  }
  try {
    execFileSync('xcrun', ['notarytool', 'history', '--keychain-profile', NOTARY_PROFILE], { stdio: 'ignore' });
  } catch {
    throw new Error(
      `No notarization credentials stored as "${NOTARY_PROFILE}". Store them once with\n` +
        `  xcrun notarytool store-credentials ${NOTARY_PROFILE} --key <AuthKey.p8> --key-id <id> --issuer <issuer>\n` +
        'as RELEASING.md describes.',
    );
  }
}

// --- 1. the .app --------------------------------------------------------------------------

say(`packaging ${NAME} ${pkg.version} for ${ARCH}`);
rmSync(DIST, { recursive: true, force: true });
const [folder] = await packager({
  dir: here,
  out: DIST,
  name: NAME,
  executableName: NAME,
  platform: 'darwin',
  arch: ARCH,
  electronVersion: createRequire(import.meta.url)('electron/package.json').version,
  appBundleId: BUNDLE_ID,
  appCategoryType: 'public.app-category.productivity',
  appVersion: pkg.version,
  buildVersion: pkg.version,
  appCopyright: 'Peter Harding',
  icon: join(here, 'assets', 'icon.icns'),
  asar: true,
  // The app is out/ and package.json and nothing else: every dependency is bundled into
  // out/ by build.mjs, and node:sqlite comes with Electron.
  ignore: (path) => !(path === '' || path === '/package.json' || path === '/out' || path.startsWith('/out/')),
  prune: false,
  overwrite: true,
  quiet: true,
});
const app = join(folder, `${NAME}.app`);

if (!release) {
  // Apple silicon runs nothing unsigned; an ad-hoc signature makes a local build launch.
  run('codesign', ['--force', '--deep', '--sign', '-', app]);
  say(`built ${app} (ad hoc; make browser-release signs and notarizes)`);
  process.exit(0);
}

// --- 2. signed, notarized, stapled --------------------------------------------------------

say(`signing with ${IDENTITY}`);
await sign({
  app,
  identity: IDENTITY,
  platform: 'darwin',
  // The app takes our entitlements; its helpers keep osx-sign's defaults, JIT only.
  optionsForFile: (file) => (file === app ? { hardenedRuntime: true, entitlements: ENTITLEMENTS } : { hardenedRuntime: true }),
});
run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', app]);

say('notarizing the app (Apple takes a few minutes)');
await notarize({ appPath: app, keychainProfile: NOTARY_PROFILE }); // staples when accepted
run('xcrun', ['stapler', 'validate', app]);
run('spctl', ['--assess', '--type', 'execute', '--verbose=2', app]);

// --- 3. the zip for updates, and the DMG to install from ----------------------------------

const zip = join(DIST, `${NAME}-${pkg.version}-darwin-${ARCH}.zip`);
say(`zipping ${zip}`);
run('ditto', ['-c', '-k', '--sequesterRsrc', '--keepParent', app, zip]);

const dmg = join(DIST, `${NAME}-${pkg.version}-${ARCH}.dmg`);
say(`making ${dmg}`);
const staging = mkdtempSync(join(tmpdir(), 'smart-browser-dmg-'));
try {
  run('ditto', [app, join(staging, `${NAME}.app`)]);
  symlinkSync('/Applications', join(staging, 'Applications')); // drag the app onto this
  run('hdiutil', ['create', '-volname', `${NAME} ${pkg.version}`, '-srcfolder', staging, '-ov', '-format', 'UDZO', dmg]);
} finally {
  rmSync(staging, { recursive: true, force: true });
}
run('codesign', ['--sign', IDENTITY, '--timestamp', dmg]);
say('notarizing the DMG');
await notarize({ appPath: dmg, keychainProfile: NOTARY_PROFILE });
run('spctl', ['--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=2', dmg]);

say(`released ${pkg.version}:\n  ${dmg}\n  ${zip}`);
