// Renders icon.svg into icon.icns, the app's icon (ADR 0018). Run with Electron, which
// draws the SVG exactly as Chromium does, then macOS's iconutil packs the sizes:
//
//   npx electron assets/make-icon.cjs
//
// The .icns is committed; run this again only when icon.svg changes.

const { app, BrowserWindow } = require('electron');
const { execFileSync } = require('node:child_process');
const { mkdirSync, readFileSync, rmSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');

const here = __dirname;
const iconset = join(here, 'icon.iconset');
// Each size macOS asks for, at 1x and 2x.
const SIZES = [16, 32, 128, 256, 512];

app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false });
  await window.loadURL('about:blank');
  const svg = `data:image/svg+xml;base64,${readFileSync(join(here, 'icon.svg')).toString('base64')}`;
  rmSync(iconset, { recursive: true, force: true });
  mkdirSync(iconset);
  for (const size of SIZES) {
    for (const scale of [1, 2]) {
      const px = size * scale;
      const png = await window.webContents.executeJavaScript(`(async () => {
        const image = new Image();
        image.src = ${JSON.stringify(svg)};
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = ${px};
        const context = canvas.getContext('2d');
        context.imageSmoothingQuality = 'high';
        context.drawImage(image, 0, 0, ${px}, ${px});
        return canvas.toDataURL('image/png');
      })()`);
      const name = scale === 1 ? `icon_${size}x${size}.png` : `icon_${size}x${size}@2x.png`;
      writeFileSync(join(iconset, name), Buffer.from(png.split(',')[1], 'base64'));
    }
  }
  execFileSync('iconutil', ['-c', 'icns', iconset, '-o', join(here, 'icon.icns')]);
  rmSync(iconset, { recursive: true, force: true });
  console.log('wrote assets/icon.icns');
  app.quit();
});
