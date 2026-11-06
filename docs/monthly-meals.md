# Monthly menus and specialist shopping

Open **Meals → Plan a month of meals**, or **More tools → Monthly meals & shops**. Choose a calendar month, then **Create / complete monthly menu**. This is a dinner menu with the recipes' next-day lunch extras, not a complete breakfast/snack/household plan.

The month is backed by the same private Sunday-start weekly files used by the daily receipt. Existing meals and eating-out/freezer overrides are retained; missing upcoming weeks/days are filled. New choices retain diet, allergen and weekday-time rules, favour shared components and penalise repeats from earlier weeks in the month. Existing saved recipes that conflict with current rules are flagged for review rather than silently replaced. Use each day’s **Change this meal** to edit upcoming, uneaten meals. The edited week feeds the regular receipt and shopping. Generating another overlapping month preserves already planned boundary days.

## Shopping pattern

The default supplier pattern is:

- **Main supermarket shop:** combined store-cupboard and explicitly frozen items for remaining meals.
- **Butcher:** weekly meat requirements, preserving cut/ingredient names and compatible units.
- **Greengrocer:** weekly fresh produce, optionally split by a second midweek shopping day.
- **Supermarket top-up:** fresh essentials and fish by default. Assign these to a local shop, greengrocer or fishmonger where the supplier stocks those items.

Select a shared weekly day to combine stops into an outing. The report counts shopping days, shop stops and supermarket stops separately. These are suggested purchase groupings, not opening-hour checks, optimised journeys or a promise that weekly trips are always sufficient. The first incomplete week can require a catch-up purchase before the normal shopping day. Remaining requirements regroup from the date you view the month; purchases are not automatically tracked or ordered.

Correct individual ingredient categories where automatic classification does not suit the product. Explicit tins/frozen/dried foods and dry staples are separated from fresh products; unknown foods default to fresh essentials. Category corrections persist across future menus. Fresh supplier categories cannot be assigned to the monthly main-shop schedule wholesale. Assign an individual product to cupboard/freezer only after checking its actual packaging, suitability and available freezer space.

Compatible recipe quantities are summed before pack/count rounding. Different cuts, measurement types and incompatible units remain separate. Unmeasured quantities remain visible; no density or weight-per-piece is invented. Items recorded in the pantry remain visible with a stock-check note, since a name or boolean entry does not establish enough stock for a whole month. Amounts use the recipes as written; additional guests, drinks, snacks and household essentials need separate allowance.

Bought prep components missing from a recipe's literal ingredients are included as explicit shopping requirements, using the same weekly make/buy decisions as the receipt. Missing amounts remain marked. Homemade component ingredients and original preparation yields are shown separately for manual checking; they are not guessed or automatically scaled. The existing conservative component batching/storage policy still applies.

## Storage and scope

A shopping date is not a shelf-life guarantee. Follow use-by dates, opened-pack instructions and safe chilled/frozen storage; buy closer to use if a product cannot be kept, or freeze suitable portions before their use-by date. Do not treat a monthly menu as permission to refrigerate a month of meat/veg or keep one homemade sauce batch all month. The usual Meals storage/leftovers guide remains available. Guidance checked against:

- [FSA: chilling, freezing and defrosting](https://www.gov.uk/government/publications/how-to-chill-freeze-and-defrost-food-safely/how-to-chill-freeze-and-defrost-food-safely)
- [Best before and use-by dates](https://www.gov.uk/understanding-food-labelling/best-before-and-use-by-dates)

Menu cost is the recipes' existing estimate, not live prices or a complete household budget; components, quantities, pack sizes and specialist prices can change the actual total. This page does not send orders, choose a real shop, insert errands, change retailer baskets or replace the existing Tesco review. The daily receipt uses the saved menu without adding a month-long shopping section to the daily paper.

## Local files

Weekly menus remain in `meal_plans/`. Shopping-day, supplier and ingredient-category preferences live in `data/monthly_meals.json`: bounded, validated, locked and atomically written with owner-only permissions. Both are ignored by Git and excluded from the ordinary allowlisted backup; include them in a protected local backup if needed. Invalid saved weekly plans are not overwritten by monthly generation. Generating is local and bounded to the weeks needed for the selected month; page reads do not generate menus or contact providers. Controls use the application's existing login, CSRF and no-store protections.
