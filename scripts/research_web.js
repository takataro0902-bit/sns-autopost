// 他アカウントの公開ページ（ログインなし）を開いて文字だけ保存する。読むだけ・投稿しない
const {chromium} = require('playwright');
const fs = require('fs');
if (!fs.existsSync('.research-web.json')) { console.log('調べる先（.research-web.json）がないので何もしません'); process.exit(0); }
const req = JSON.parse(fs.readFileSync('.research-web.json', 'utf8'));
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({locale: 'ja-JP', viewport: {width: 1200, height: 2000}});
  fs.mkdirSync('research/web', {recursive: true});
  for (const u of req.urls) {
    const p = await ctx.newPage();
    let text = '';
    try {
      await p.goto(u, {waitUntil: 'domcontentloaded', timeout: 60000});
      await p.waitForTimeout(5000);
      for (let i = 0; i < (req.scrolls || 8); i++) { await p.mouse.wheel(0, 3000); await p.waitForTimeout(1500); }
      text = await p.evaluate(() => document.body.innerText);
    } catch (e) { text = 'ERR ' + e.message; }
    const name = u.replace(/https?:\/\/[^/]+\//, '').replace(/[^\w@-]+/g, '_').slice(0, 80) || 'top';
    fs.writeFileSync(`research/web/${name}.txt`, u + '\n\n' + text);
    console.log(u, text.length);
    await p.close();
  }
  await b.close();
})();
