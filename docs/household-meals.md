# Household meals, breakfasts and seasonal choices

Open **Settings → Household & meal settings**, or the same link at the top of **Meals**. Save one profile for each diner. Names may be labels. Birth year is optional and updates the approximate age range as the year changes. Standard portion factors are user choices; they are never calculated from calorie references. Existing dinner quantities remain unchanged until household preferences are saved.

## Generated menus

Shared dishes respect the combined household diets, declared allergens and ingredient exclusions, as well as existing global meal restrictions. Ingredient-text checks supplement metadata but cannot verify labels, cross-contact, clinical suitability or the complete recipe. Notes are for manual review, not automatic medical rules. Children possibly under two are excluded from shared adult menus and need a separate feeding plan. Whole nuts are excluded for possible under-fives; check texture, preparation and all product labels yourself.

Choose **Omnivore**, **Pescatarian**, **Vegetarian** or **Vegan**. Pescatarian allows fish and shellfish but excludes meat and meat stock. Custom fish recipes can be marked pescatarian. Use **Gluten-free (coeliac)** with any diet; it screens for declared and recognisable gluten risks and replaces standard planned lunch bread or tortillas with gluten-free products. Recipes with separate prep components are omitted in this mode because component substitutions cannot be checked. Check product labels and avoid cross-contact; choose oats labelled gluten-free only if tolerated, or add oats to **Avoid**. See [NHS coeliac guidance](https://www.nhs.uk/conditions/coeliac-disease/treatment/).

Use **Food exclusions** for dairy, eggs, soya, nuts and other listed allergens, or **Avoid** for other ingredient preferences. Certification, sourcing and preparation requirements such as halal or kosher need manual verification.

Enable all eligible meals or select favourites. Add/edit custom breakfast and dinner recipes with ingredients for the **whole cooking yield** and explicit methods, minutes, diet flags and allergens. Numbers with recognised units scale to the household's chosen portions. Unmeasured ingredients are marked for review. Planned next-day lunch extras are included unless the next day is Away or has a buy/eat-out lunch override. Batch recipes retain at least their original yield. Methods, time, pan capacity and safe storage do not automatically scale.

Saved past/eaten meals are retained. Complete the monthly menu to replace incompatible future choices. Current dinner lookup refreshes an incompatible upcoming recipe; if no eligible recipe exists, the application asks for review rather than ignoring an exclusion. Changing a recipe's contents can change planned meals and shopping even when its name stays the same. Review the menu after editing settings.

**Prefer UK seasonal fresh produce** is on by default and can be turned off. It gives a modest selection preference based on the date of each meal, using broad UK seasons, including common stored winter crops. It is not live shop availability or a guarantee that produce is locally grown. Tinned/frozen/dried foods are neutral; dietary and preparation limits always take priority. Breakfast fruit also changes by season. The variety preference favours plants, wholegrains, fish where suitable and less processed meat. Menu indicators are counts of selected dishes, not a nutrient analysis or proof of a complete balanced diet; other meals, snacks, drinks and individual needs still matter.

## Dietary checks from shopping to serving

Active restrictions show a checklist on Meals and Monthly meals, a product check on Tesco shopping review, and short reminders on the food receipt. Review the exact labels on pantry items, packaged ingredients, toppings and substitutes. Restricted weekly shopping keeps pantry matches visible for this check. Home recipes and manual recipe replacements use the same filters; known ingredients and allergens from both made and bought prep components are screened. An unidentified component cannot be planned with active ingredient restrictions. Record everything used in a custom recipe, including cooking fats and optional toppings.

Keep checked ingredients and prepared batches sealed, labelled and separate from excluded foods. Clean hands, surfaces and utensils before preparing meals; use separate equipment when you cannot clean it reliably. With the coeliac filter, the checklist calls out crumbs, toaster bags or a separate toaster, shared oil, cooking water and spreads. Check sides and garnishes and use clean serving equipment. Set aside packed lunches before serving and label leftovers with the dish, date and requirements. The existing chilling, freezing and reheating times still apply. Check freezer meals and meals bought elsewhere individually; the planner cannot confirm their ingredients or handling.

See the [FSA home allergy guidance](https://www.food.gov.uk/print/pdf/node/22201) and [Coeliac UK cross-contact advice](https://www.coeliac.org.uk/living-with-coeliac-disease/food-and-drink/cooking-at-home/cross-contamination/).

## Breakfast and the calendar

Weekdays use the short preparation limit (default five minutes). More involved weekend choices need a free breakfast-window slot covering preparation plus eating/tidying. The planner reads saved calendar coverage and matching saved travel times locally; it does not make network calls to render a menu. Only fresh, explicitly checked coverage is verified. Unknown appointment ends, all-day events and travel block time conservatively. Missing calendar or morning journey information uses a quick fallback unless you explicitly allow provisional choices. Refresh **Calendar** and **Routes & times** after changing appointments. New coverage can change a suggested breakfast and its groceries.

Use the breakfast selector to choose another eligible option; manual choices are labelled if they exceed the automatic time limit. Mark breakfast eaten on the Meals page to remove it from remaining monthly shopping. The food receipt adds only two short breakfast lines, without printing private birth years or dietary profiles. Turning off breakfast leaves dinner planning available.

Monthly supplier lists include remaining breakfasts, dinners and planned lunch extras. Costs remain the existing dinner/lunch recipe estimates, **excluding breakfast prices and unknown custom recipe costs**. Pantry names do not establish sufficient stock. Follow use-by dates, opened-pack instructions and the existing storage guidance; a monthly purchase grouping is not permission to keep fresh food for a month.

## Age and energy references

Figures come from **SACN 2011 Tables 15 and 16**, including the adult population PAL 1.63 assumption. Birth year gives two possible ages, so the displayed range includes both; choose the male/female population table or a range across both. These are population reference values, not personal calorie recommendations, limits, weight-loss targets or automatic portion sizes. Activity, growth, pregnancy/breastfeeding and health can change individual needs. No energy figure is generated for possible under-twos or a profile marked as needing individual clinical/feeding advice. Recipe kcal, where supplied, are approximate values per standard portion and are separate from these population references.

## Emergency supplies

The UK Be Ready checklist recommends **three days** of non-perishable food needing no cooking or refrigeration and **three litres of stored drinking water per person per day**. The settings show that baseline while allowing a different reserve horizon, water goal, existing stock and notes. Stored water is an emergency stock calculation, not a drinking prescription; other uses can need more.

Food options are filtered for the household but are not a complete diet or guarantee of adequate energy. Set targets yourself in packs/labelled portions and record stock in the same units; the application shows the difference without inventing government tin counts. Infant feeding, formula/sterilisation and clinical needs require a separate plan. Prefer single-serving packs when opened food would need refrigeration. Build gradually, rotate supplies and review every six months. Emergency supplies remain separate from ordinary monthly groceries so they are not repeatedly bought.

## Local data and security

Profiles, birth years, dietary information, custom recipes, breakfast overrides and reserve notes are saved in `data/meal_household.json`. It uses bounded, validated reads and locked atomic owner-only writes. Invalid data is not overwritten with defaults. This file and its lock are ignored by Git and excluded from the ordinary allowlisted backup; include it in a protected local backup if needed. It is not encrypted at rest. Use the application's authenticated HTTPS setup and protect the host and its backups. These pages use existing login, CSRF and no-store protections; preferences are not sent to an external nutrition service.

## Sources

Guidance and factual tables checked 7 November 2026:

- [SACN dietary reference values for energy](https://www.gov.uk/government/publications/sacn-dietary-reference-values-for-energy), Tables 15/16 and the limits on applying population references to individuals.
- [NHS Eatwell Guide](https://www.nhs.uk/live-well/eat-well/food-guidelines-and-food-labels/the-eatwell-guide/).
- [Soil Association seasonal food guide](https://www.soilassociation.org/what-we-do/championing-organic/seasonal-food/).
- [UK government Be Ready emergency checklist](https://beready.campaign.gov.uk/be-ready-for-emergencies/).
- [NHS foods to avoid for babies and young children](https://www.nhs.uk/baby/weaning-and-feeding/foods-to-avoid-giving-babies-and-young-children/).
- [NHS safe food preparation for weaning](https://www.nhs.uk/best-start-in-life/baby/weaning/safe-weaning/preparing-food-safely/).
