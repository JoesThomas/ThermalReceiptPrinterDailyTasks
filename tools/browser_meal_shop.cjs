/* Verify the dated checklist and queue a single saved receipt. */
module.exports = async function(page) {
  const assert = require('node:assert/strict');
  const settings = page.locator('form[action="/meals/month/settings"]');
  await settings.locator('[name=shop_4]').selectOption('Supermarket top-up');
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),settings.getByRole('button',{name:'Save shopping preferences',exact:true}).click()]);
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('link',{name:'Supermarket checklist & print',exact:true}).click()]);
  await page.getByRole('heading',{name:'Supermarket shopping checklist',exact:true}).waitFor();
  const checks = page.locator('input[data-shop-amount]:checked');
  assert.ok(await checks.count() > 0);
  const phone = page.locator('#shop-mode');
  await phone.waitFor();
  await phone.locator('[data-shop-got]').first().check();
  await phone.locator('[data-shop-state]').nth(1).selectOption('missing');
  await page.reload();
  assert.equal(await phone.locator('[data-shop-got]').first().isChecked(),true);
  assert.equal(await phone.locator('[data-shop-state]').nth(1).inputValue(),'missing');
  assert.match(await phone.locator('#shop-progress').innerText(),/1 got.*1 couldn’t find/);
  await page.getByText('Copy shopping list instead',{exact:true}).click();
  const text = page.locator('#shop-copy-text');
  const before = await text.inputValue();
  assert.doesNotMatch(before,/chicken breast|carrot/);
  await checks.first().uncheck();
  assert.equal((await text.inputValue()).split('\n').length,before.split('\n').length-1);
  await checks.first().waitFor();
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('button',{name:'Print shopping checklist',exact:true}).click()]);
  await page.locator('.flash').filter({hasText:'Shopping checklist queued for printing'}).waitFor();
  const args = await page.evaluate(async () => (await fetch('/__fixture_last_print')).json());
  assert.equal(args[0],'--archive');
  assert.equal(args[2],'all');
  for(const width of [390,1280]) {
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Shopping list overflows');
  }
  const a11y = await require('./browser_accessibility.cjs')(page,'/meals/shop');
  await page.goto('http://receipt.test/tasks');
  const butcher = page.getByRole('link',{name:'Open Butcher shopping list',exact:true}).first();
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),butcher.click()]);
  await page.getByRole('heading',{name:'Butcher shopping checklist',exact:true}).waitFor();
  assert.match(await page.locator('#shop-copy-text').inputValue(),/chicken breast/);
  return a11y;
};
