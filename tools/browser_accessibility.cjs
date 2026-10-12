/* Accessibility checks use only the same synthetic pages as browser form tests. */
const assert = require('node:assert/strict');
module.exports = async (page, path) => {
  await page.addScriptTag({content:require('axe-core').source});
  const results = await page.evaluate(async () => window.axe.run(document, {
    runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}
  }));
  const failures = results.violations.map(row => ({rule:row.id,help:row.help,targets:row.nodes.map(node=>node.target)}));
  assert.deepEqual(failures, [], `Accessibility violations on ${path}: ${JSON.stringify(failures)}`);
};
