/* Real household forms; dietary choices must change the generated menu. */
module.exports = async function(page) {
  const assert = require('node:assert/strict');
  await page.goto('http://receipt.test/meals/settings');
  const recipe = page.locator('form[action="/meals/settings/recipe"]').last();
  await recipe.locator('[name=name]').fill('Household lentil rice');
  await recipe.locator('[name=ingredients]').fill('200g lentils\n150g rice\n2 carrots');
  await recipe.locator('[name=method]').fill('Cook lentils and rice according to their packs. Cook chopped carrots until tender.');
  await recipe.locator('[name=servings]').fill('2');
  await recipe.locator('[name=vegan]').check();
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),recipe.getByRole('button',{name:'Save custom recipe',exact:true}).click()]);
  const form = page.locator('form[action="/meals/settings/household"]');
  await form.locator('[name=person_name_0]').fill('Adult');
  await form.locator('[name=birth_year_0]').fill('1996');
  await form.locator('[name=diet_0]').selectOption('pescatarian');
  await form.locator('[name=coeliac_0]').check();
  await form.getByRole('button',{name:'Add person',exact:true}).click();
  await form.locator('[name=person_name_1]').fill('Child');
  await form.locator('[name=birth_year_1]').fill('2023');
  await form.locator('[name=diet_1]').selectOption('vegan');
  await form.locator('[name=portion_1]').fill('0.5');
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),form.getByRole('button',{name:'Save household & meal preferences',exact:true}).click()]);
  assert.equal(await form.locator('fieldset.person-fields').count(),2);
  assert.equal(await form.locator('[name=seasonal]').isChecked(),true);
  assert.equal(await form.locator('[name=diet_0]').inputValue(),'pescatarian');
  assert.equal(await form.locator('[name=coeliac_0]').isChecked(),true);
  assert.match(await page.locator('#energy').innerText(),/not personal recommendations/);
  const reserve=page.locator('form[action="/meals/settings/reserve"]');
  await reserve.locator('[name=water_have]').fill('5');
  await reserve.locator('[name=target_beans]').fill('6');
  await reserve.locator('[name=have_beans]').fill('2');
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),reserve.getByRole('button',{name:'Save reserve settings',exact:true}).click()]);
  assert.match(await page.locator('#emergency-food').innerText(),/18(?:\.0)? litres; missing: 13/);
  assert.equal(await reserve.locator('[name=target_nuts]').count(),0);
  const failures=[];
  for (const path of ['/meals/settings','/meals']) {
    await page.goto('http://receipt.test'+path);
    for(const width of [390,1280]) {
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,path+' overflows');
      if(process.env.HOUSEHOLD_SCREENSHOT) await page.screenshot({path:process.env.HOUSEHOLD_SCREENSHOT+'-'+path.replaceAll('/','-')+'-'+width+'.png',fullPage:false});
    }
    const a11y=await require('./browser_accessibility.cjs')(page,path);
    if(a11y) failures.push(a11y);
  }
  const handling = page.getByText('Dietary checks: shopping to serving',{exact:true});
  await handling.click();
  await page.getByText('Pack leftovers',{exact:true}).waitFor();
  assert.equal(await page.locator('#planned-recipe option[value^="Monthly fixture dinner"]').count(),0);
  const rejected = await page.evaluate(async () => {
    const form = document.querySelector('form[action="/meals/plan"]');
    const data = new URLSearchParams(new FormData(form));
    data.set('recipe','Monthly fixture dinner 0');
    return (await fetch(form.action,{method:'POST',body:data})).status;
  });
  assert.equal(rejected,400);
  assert.match(await page.locator('main').innerText(),/Breakfast/);
  await page.goto('http://receipt.test/__fixture_monthly_meals');
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),page.getByRole('button',{name:'Create / complete monthly menu',exact:true}).click()]);
  assert.match(await page.locator('.month-day').first().innerText(),/Household lentil rice/);
  assert.doesNotMatch(await page.locator('.month-day').first().innerText(),/Monthly fixture dinner/);
  const day = page.locator('.month-day').first();
  await day.getByText("Who's eating?",{exact:true}).click();
  const attendance = day.locator('form[action="/meals/month/attendance"]');
  await attendance.locator('input[value$=":dinner"]').first().check();
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),attendance.getByRole('button',{name:'Save attendance',exact:true}).click()]);
  await page.locator('p.flash').filter({hasText:'Attendance saved'}).waitFor();
  await day.locator('summary').filter({hasText:'attendance changed'}).click();
  assert.match(await attendance.locator('..').innerText(),/1 dinner/);
  await attendance.locator('input[value$=":dinner"]').last().check();
  await Promise.all([page.waitForNavigation({waitUntil:'load'}),attendance.getByRole('button',{name:'Save attendance',exact:true}).click()]);
  assert.match(await day.innerText(),/No dinner needed/);
  const a11y=await require('./browser_accessibility.cjs')(page,'/meals/month');
  if(a11y) failures.push(a11y);
  return failures;
};
