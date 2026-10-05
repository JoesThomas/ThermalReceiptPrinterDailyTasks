/* Real forms and templates, with external collection replaced by local fixtures. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const readline = require('node:readline');
const child = spawn(process.env.RECEIPT_TEST_PYTHON || 'python', ['tools/browser_smoke_server.py', '--stdio'], {stdio:['pipe','pipe','inherit']});
const waiting = [];
readline.createInterface({input:child.stdout}).on('line', line => { const item=waiting.shift(); if (item) item.resolve(JSON.parse(line)); });
let queue=Promise.resolve();
function request(value) {
  const result=queue.then(() => new Promise((resolve,reject) => {waiting.push({resolve,reject});child.stdin.write(JSON.stringify(value)+'\n');}));
  queue=result.catch(() => {}); return result;
}
process.on('exit', () => child.kill());
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.RECEIPT_BROWSER_BINARY || undefined, args: ['--no-sandbox']});
  const page = await browser.newPage();
  await page.route('**/*', async route => {
    const req=route.request(), url=new URL(req.url());
    if (url.hostname !== 'receipt.test') return route.abort();
    const headers=req.headers(); delete headers.host; delete headers.cookie;
    const result=await request({path:url.pathname+url.search, method:req.method(), body:req.postData() || '', headers});
    if (result.status >= 300 && result.status < 400 && result.headers.Location) {
      return route.fulfill({status:200, contentType:'text/html', body:`<script>location.replace(${JSON.stringify(result.headers.Location)})</script>`});
    }
    await route.fulfill({status:result.status, headers:result.headers, body:Buffer.from(result.body,'base64')});
  });
  await page.goto('http://receipt.test/__fixture_login');
  await page.locator('#manual-collections').fill('2026-10-06 | Recycling | 14');
  await Promise.all([page.waitForURL('**/bins'), page.getByRole('button', {name: 'Use manual schedule'}).click()]);
  await page.locator('main').getByText('Manual schedule saved and selected.', {exact:true}).waitFor();
  await page.goto('http://receipt.test/?view=accounts');
  const form = page.locator('form[action$="/commitment/add"]');
  await form.evaluate(el => { for (let parent = el.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true; });
  await form.locator('input[name=name]').fill('Example subscription');
  await form.locator('input[name=amount]').fill('12.34');
  await Promise.all([page.waitForURL(url => url.hash === '#commitments'), form.locator('button').click()]);
  assert.match(await page.locator('main').innerText(), /Example subscription/);
  await page.goto('http://receipt.test/deliveries');
  const delivery = page.locator('form[action$="/deliveries/confirm"]').first();
  await delivery.locator('input[type=checkbox]').check();
  await Promise.all([page.waitForURL('**/deliveries'), delivery.getByRole('button', {name:'Save'}).click()]);
  await page.getByText('Received history', {exact:true}).click();
  assert.equal(await page.locator('input[type=checkbox]:checked').count(), 1);
  await page.goto('http://receipt.test/preferences');
  const cards = page.locator('form[action$="/preferences/cards"]');
  await cards.locator('input[name=name]').fill('Test card');
  await cards.locator('input[name=limit]').fill('2000');
  await cards.locator('input[name=used]').fill('600');
  await Promise.all([page.waitForURL('**/preferences#credit-cards'), cards.getByRole('button', {name:'Save card limit'}).click()]);
  assert.match(await page.locator('#credit-cards').innerText(), /30.0% used/);
  await page.goto('http://receipt.test/finance/tax');
  const tax = page.locator('form[action$="/finance/tax"]');
  assert.equal(await page.evaluate(async () => (await fetch('/finance/tax', {method:'POST',body:new URLSearchParams({enabled:'on'})})).status),403);
  await tax.locator('input[name=enabled]').check();
  for (const field of ['other_income','expenses','interest','losses','finance_carried','reserved']) await tax.locator(`input[name=${field}]`).fill('0');
  await tax.locator('input[name=rent]').fill('9600');
  await Promise.all([page.waitForURL('**/finance/tax'), tax.getByRole('button', {name:'Save and calculate'}).click()]);
  assert.match(await page.locator('main').innerText(), /Estimated additional rental tax/);
  assert.match(await page.locator('main').innerText(), /£0.00/);
  await page.goto('http://receipt.test/preview?source=live');
  const preview = page.locator('form[action$="/preview/generate"]').last();
  await Promise.all([page.waitForURL('**/preview?source=live'), preview.locator('button').first().click()]);
  assert.match(await page.locator('main').innerText(), /Fixture receipt generated/);
  let checks = 0;
  for (const width of [360,390,768,1280]) {
    await page.setViewportSize({width,height:900});
    for (const path of ['/bins','/deliveries','/?view=accounts','/preview?source=live','/preferences','/finance/explanations','/finance/tax']) {
      await page.goto('http://receipt.test'+path);
      await page.locator('details').evaluateAll(rows => rows.forEach(row => row.open=true));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth+2), false, `${path} overflows at ${width}`);
      checks++;
    }
  }
  if (process.env.RECEIPT_BROWSER_SCREENSHOT) {
    await page.setViewportSize({width:390,height:900});
    await page.goto('http://receipt.test/bins');
    await page.screenshot({path:process.env.RECEIPT_BROWSER_SCREENSHOT, fullPage:true});
  }
  console.log(`Browser checks passed: 6 form flows, ${checks} responsive layouts`);
  await browser.close();
  child.kill();
})().catch(error => { console.error(error); process.exit(1); });
