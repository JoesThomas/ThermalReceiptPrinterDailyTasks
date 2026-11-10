/* Check the hands-on recipe view using the synthetic saved meal plan. */
module.exports = async function(page) {
  const assert = require('node:assert/strict');
  await page.goto('http://receipt.test/meals');
  const planned = (await page.getByRole('heading',{name:'Planned meal',exact:true})
    .locator('..').locator('p strong').first().innerText()).trim();
  await page.getByRole('link',{name:'Open Kitchen mode',exact:true}).click();
  await page.getByRole('heading',{name:planned,exact:true}).waitFor();
  const steps = page.locator('[data-step]:visible');
  const ingredients = page.locator('[data-ingredient]');
  assert.equal(await steps.count(),1);
  await ingredients.first().check();
  await page.getByRole('button',{name:'Next step',exact:true}).click();
  assert.equal(await steps.innerText(),'Cook the meal');
  await page.reload();
  assert.equal(await steps.innerText(),'Cook the meal');
  assert.equal(await ingredients.first().isChecked(),true);
  await page.getByRole('button',{name:'Show all steps',exact:true}).click();
  assert.equal(await steps.count(),3);
  await page.getByRole('button',{name:'Show one step',exact:true}).click();
  await page.getByRole('button',{name:'Clear ticks',exact:true}).click();
  assert.equal(await ingredients.first().isChecked(),false);
  for(const [width,height] of [[390,844],[768,1024],[1024,768]]) {
    await page.setViewportSize({width,height});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  }
  const alternate = planned.endsWith('8') ? 'Monthly fixture dinner 7' : 'Monthly fixture dinner 8';
  await page.getByLabel('Recipe',{exact:true}).selectOption(alternate);
  await page.getByRole('button',{name:'Open recipe',exact:true}).click();
  await page.getByRole('heading',{name:alternate,exact:true}).waitFor();
  assert.equal(await steps.innerText(),'Prepare the ingredients');
  await page.goto('http://receipt.test/meals/cook');
  await page.getByRole('heading',{name:planned,exact:true}).waitFor();
  return require('./browser_accessibility.cjs')(page,'/meals/cook');
};
