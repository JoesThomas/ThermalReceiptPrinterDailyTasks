/* Verify the saved retailer, dated ingredients, and clipboard selection. */
module.exports = async function(page) {
  const assert = require('node:assert/strict');
  const settings = page.locator('form[action="/meals/month/settings"]');
  await settings.locator('[name=retailer]').selectOption('waitrose');
  await settings.locator('[name=shop_4]').selectOption('Supermarket top-up');
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),settings.getByRole('button',{name:'Save shopping preferences',exact:true}).click()]);
  assert.equal(await settings.locator('[name=retailer]').inputValue(),'waitrose');
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('link',{name:'Prepare supermarket shopping list',exact:true}).click()]);
  await page.getByRole('heading',{name:'Shop at Waitrose & Partners',exact:true}).waitFor();
  const checks = page.locator('input[data-shop-amount]:checked');
  assert.ok(await checks.count() > 0);
  assert.equal(await page.getByRole('link',{name:/Find .*chicken breast.* at Waitrose/}).count(),0);
  assert.equal(await page.getByRole('link',{name:/Find .*carrot.* at Waitrose/}).count(),0);
  const text = page.locator('#shop-copy-text');
  const before = await text.inputValue();
  await checks.first().uncheck();
  assert.equal((await text.inputValue()).split('\n').length,before.split('\n').length-1);
  assert.match(await page.getByRole('link',{name:/Find .* at Waitrose/}).first().getAttribute('href'),/^https:\/\/www\.waitrose\.com\/ecom\/shop\/search\?/);
  assert.equal(await page.getByRole('button',{name:'Create basket review',exact:true}).count(),0);
  const options = page.locator('[name=day] option');
  await page.getByLabel('Shopping date',{exact:true}).selectOption(await options.last().getAttribute('value'));
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('button',{name:'Show ingredients',exact:true}).click()]);
  assert.notEqual(await text.inputValue(),before);
  for(const width of [390,1280]) {
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Shopping list overflows');
  }
  const a11y = await require('./browser_accessibility.cjs')(page,'/meals/shop');
  await page.goto('http://receipt.test/tasks');
  const butcher = page.getByRole('link',{name:'Open Butcher shopping list',exact:true}).first();
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),butcher.click()]);
  await page.getByRole('heading',{name:'Butcher shopping list',exact:true}).waitFor();
  assert.match(await page.locator('#shop-copy-text').inputValue(),/chicken breast/);
  assert.equal(await page.getByRole('button',{name:'Create basket review',exact:true}).count(),0);
  return a11y;
};
