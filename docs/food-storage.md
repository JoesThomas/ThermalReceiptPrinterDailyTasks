# Food storage and leftovers

The Meals page has a bulk-prep reference and guidance for today's recipe.
Sunday prep receipts show guidance for each homemade component; daily recipes
show a single leftovers block, also covering the planned next-day lunch.
The existing `cooking_style.show_storage_guidance` preference controls printing;
the web reference remains available. Paper-saver mode abbreviates the wording,
keeping the storage location, handling and time limits.

Dates are **conditional planning prompts**, based on the UK date of the recipe
or Sunday prep print. They are not batch tracking: neither a generated plan nor
an eaten-meal confirmation proves when food was made, cooled, frozen or thawed.
A 48-hour limit is from the actual preparation time, not midnight on the shown
date. Earlier ingredient use-by/opened-pack instructions take precedence.

## Rules and evidence

Reviewed 19 October 2026; offline at runtime. Sources:

- [FSA chilling/freezing/defrosting](https://www.gov.uk/government/publications/how-to-chill-freeze-and-defrost-food-safely/how-to-chill-freeze-and-defrost-food-safely): fridge 0-5C, freezer around -18C, cool cooked food in small portions and refrigerate within 1-2 hours, ordinary leftovers within 48 hours or freeze, defrost in the fridge and use within 24 hours once thawed. Keep ready-to-eat food separate from raw food.
- [FSA rice/eggs guidance](https://www.gov.uk/government/publications/home-food-fact-checker/home-food-fact-checker): rice needs rapid cooling (ideally an hour), a 24-hour refrigerated limit, one reheat only; thaw frozen rice in the fridge, reheat thoroughly and eat immediately.
- [FSA cooking/reheating](https://www.gov.uk/government/publications/cooking-your-food/cooking-your-food): reheat once, thoroughly throughout.

These general sources do **not** validate the shelf life of individual homemade
sauces. Application planning choices are deliberately shorter: same-day homemade
mayo/sriracha mayo (pasteurised egg for the homemade base), 48 hours for yoghurt
dressing, pesto and quick pickles; 24 hours for raw pasta dough. Quick pickles
are refrigerated preparations, not tested shelf-stable preserves. Freezing mayo
and yoghurt dressing is not suggested. Dry spice blends use the earliest
ingredient best-before for quality rather than an invented safety deadline.
Plain focaccia uses a two-day quality planning guide; frozen bread's 3-4 month
quality guide comes from the FSA baked-goods guidance. Perishable toppings need
refrigeration. Stock follows the general 48-hour cooked-leftover rule and
must start with a safely stored carcass. None of these choices overrides shorter
ingredient limits or makes improperly handled food safe.

Frozen-food quality dates are not safety expiry dates; no generic frozen-sauce
expiry is invented. Unknown/custom component IDs get an explicit missing-period
message and their local storage note, rather than an assumed week of shelf life.
Rules are centralised in `meals/food_storage.py`, so old saved plans also benefit
without regeneration or modifications to user recipe/component files.
