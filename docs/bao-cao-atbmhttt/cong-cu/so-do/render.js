// Render các file SVG thành PNG (độ phân giải gấp 2). Chạy: node render.js <svg_dir> <png_dir> [tên...]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const [svgDir, pngDir, ...only] = process.argv.slice(2);
(async () => {
  fs.mkdirSync(pngDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 2 });
  for (const f of fs.readdirSync(svgDir).filter(f => f.endsWith('.svg'))) {
    const name = f.replace(/\.svg$/, '');
    if (only.length && !only.includes(name)) continue;
    const svg = fs.readFileSync(path.join(svgDir, f), 'utf8');
    await page.setContent(`<html><body style="margin:0">${svg}</body></html>`);
    const el = await page.$('svg');
    await el.screenshot({ path: path.join(pngDir, `${name}.png`) });
    console.log('rendered', name);
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
