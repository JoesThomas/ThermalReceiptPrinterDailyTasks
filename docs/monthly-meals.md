# Monthly menus and specialist shopping

Open **Meals → Plan a month of meals**, or **More tools → Monthly meals & shops**. Choose a calendar month, then **Create / complete monthly menu**. The menu includes dinners, their planned next-day lunch extras and optional breakfasts. See [household settings](household-meals.md) for diners, dietary filters, seasonal choices and calendar-aware breakfasts; snacks, drinks and other household needs still need separate allowance.

The month is backed by the same private Sunday-start weekly files used by the daily receipt. Existing meals and eating-out/freezer overrides are retained; missing upcoming weeks/days are filled. New choices retain diet, allergen and weekday-time rules, favour shared components and penalise repeats from earlier weeks in the month. Incompatible future, uneaten recipes are flagged for review and replaced when you complete the monthly menu; past and eaten meals remain recorded. Use each day’s **Change this meal** to edit upcoming, uneaten meals. The edited week feeds the regular receipt and shopping. Generating another overlapping month preserves already planned boundary days.

## Shopping pattern

In **Shopping days & shops**, choose **Supermarket only** for one supermarket
checklist per shopping date, or **Split between specialist shops** to route
ingredient categories separately. Changing modes preserves your supplier
choices and keeps existing weekend and freshness rules. It does not change
the saved menu.

The default split supplier pattern is:

- **Main supermarket shop:** combined store-cupboard and explicitly frozen items for remaining meals.
- **Butcher:** weekly meat requirements, preserving cut/ingredient names and compatible units.
- **Greengrocer:** weekly fresh produce, optionally split by a second weekend shopping day.
- **Baker:** bread, rolls, wraps and other bakery products on new setups.
  Existing setups keep their former fresh-essentials supplier for bakery
  items until you change it.
- **Supermarket top-up:** fresh essentials and fish by default. Assign these to a local shop, greengrocer or fishmonger where the supplier stocks those items.

Shops are scheduled on Saturday by default, with Sunday available in settings. Select a shared day to combine stops into an outing. The report counts shopping days, shop stops and supermarket stops separately. These are suggested purchase groupings, not opening-hour checks, optimised journeys or a promise that weekly trips are always sufficient. If a meal needs ingredients before the next weekend, its quantities appear under **Needed before this shop**, separate from the weekend checklist, so you can check stock or change those meals. Remaining requirements regroup from the date you view the month; purchases are not automatically tracked or ordered.

Correct individual ingredient categories where automatic classification does not suit the product. Explicit tins/frozen/dried foods and dry staples are separated from fresh products; unknown foods default to fresh essentials. Category corrections persist across future menus. Fresh supplier categories cannot be assigned to the monthly main-shop schedule wholesale. Assign an individual product to cupboard/freezer only after checking its actual packaging, suitability and available freezer space.

Each shop checklist shows one line per ingredient. Open that ingredient in the monthly view to see the meals, dates and original recipe amounts. Compatible quantities are summed before pack/count rounding. Incompatible units stay visible on the same line (for example, 6 tomatoes + 450 g tomatoes). An unmeasured ingredient gets one note rather than separate entries for every household size. Where a recipe simply says “fresh herbs”, the list suggests flat-leaf parsley as a default to use across meals, if suitable for the household. It is a suggestion, not a herb named by the recipe. Items recorded in the pantry remain visible with a stock-check note, since a name or boolean entry does not establish enough stock for a whole month. Amounts use configured household portion factors when enabled; additional guests, drinks, snacks and household essentials need separate allowance.

Generic leafy greens suggest **baby spinach**; generic salad leaves suggest **mixed salad leaves**. Recipe ingredient displays include examples for mixed salad leaves: lettuce, rocket or baby spinach. These are alternatives within one mix, not extra items to buy. Named spinach, lettuce, frozen greens and other distinct products stay separate. Explicit handfuls are estimated at **25 g per handful**, multiplied by household scaling, and combined with any exact weights for the same ingredient. The shopping line says **Approx.** and the details retain the original recipe amounts. This is an editable planning assumption in `LEAF_HANDFUL_GRAMS`, not a measured portion or a fixed bag size. Other unmeasured wording stays marked for checking.

Generic counted tomatoes suggest **medium round tomatoes**, preserving the meaning of the recipe's count. For weight-only generic tomatoes, named salad/roast-tomato dishes suggest **cherry tomatoes**, and named sauce/ragù/bolognese dishes suggest **plum tomatoes**; other uses suggest **round tomatoes**. These are labelled suggestions, not varieties specified by the recipes. Named cherry, piccolo, beef, preserved or other tomatoes are kept as written. No tomato count/weight conversions are invented.

The bundled recipe catalogue now specifies the chosen leaf, tomato type and herb rather than leaving generic produce names. Former handfuls use 25 g and unspecified herbs use 5 g flat-leaf parsley in the base recipe, with an ingredient note in Kitchen mode identifying these as planning defaults. Household portions scale the numeric amounts. Original saved menus retain their files. When displaying an older built-in recipe, its generic leafy greens and salad leaves are clarified to baby spinach and mixed salad leaves, with former handfuls estimated at 25 g before household scaling. Already-scaled quantities retain their existing factor. The clarified ingredient names are checked against household exclusions. Custom recipes are not rewritten.

Known catalogue dishes now name beef mince, strips or stewing beef explicitly. Old saved shopping requirements for those exact recipe names are clarified too, so identical mince requirements combine. Custom recipes and explicitly named cuts are left alone.

**Prefer a whole chicken when multiple cuts are needed** is on by default under **Shopping days & shops**. The list combines counted breasts or thighs for the same shop when a bird supplies at least two planned cuts. Open **Whole chicken** in the monthly list to see which meals get those cuts. A single cut on its own and cuts measured by weight stay on the list as written; the planner does not automatically substitute a bird for weighed cuts. When weighed breast or thigh is needed, the optional size guide rounds up using 18% breast and 10% thigh by dressed bird weight as rough planning assumptions, informed by [retail carcass yields](https://revistas.usp.br/aesalq/en/article/view/5121) and the [Cobb broiler breakdown](https://www.cobb-vantress.com/assets/Cobb-Files/999edfa279/Broiler-Yield-Poster-English.pdf). Actual yield varies; confirm with the butcher, especially if the same bird needs to cover counted cuts too. The saved recipes stay the same. Use or freeze remaining suitable portions and consider using the carcass for stock.

Bought prep components missing from a recipe's literal ingredients are included as explicit shopping requirements, using the same weekly make/buy decisions as the receipt. Missing amounts remain marked. Homemade component ingredients and original preparation yields are shown separately for manual checking; they are not guessed or automatically scaled. The existing conservative component batching/storage policy still applies.

## Storage and scope

A shopping date is not a shelf-life guarantee. Follow use-by dates, opened-pack instructions and safe chilled/frozen storage; buy closer to use if a product cannot be kept, or freeze suitable portions before their use-by date. Do not treat a monthly menu as permission to refrigerate a month of meat/veg or keep one homemade sauce batch all month. The usual Meals storage/leftovers guide remains available. Guidance checked against:

- [FSA: chilling, freezing and defrosting](https://www.gov.uk/government/publications/how-to-chill-freeze-and-defrost-food-safely/how-to-chill-freeze-and-defrost-food-safely)
- [Best before and use-by dates](https://www.gov.uk/understanding-food-labelling/best-before-and-use-by-dates)

Menu cost is the existing dinner/lunch recipe estimate, excluding breakfast prices and unknown custom recipe costs; it is not live prices or a complete household budget; components, quantities, pack sizes and specialist prices can change the actual total. The shopping checklist is generated locally. The daily receipt uses the saved menu without adding a month-long shopping section to the daily paper.

## Local files

Weekly menus remain in `meal_plans/`. Shopping-day, supplier and ingredient-category preferences live in `data/monthly_meals.json`: bounded, validated, locked and atomically written with owner-only permissions. Both are ignored by Git and excluded from the ordinary allowlisted backup; include them in a protected local backup if needed. Invalid saved weekly plans are not overwritten by monthly generation. Generating is local and bounded to the weeks needed for the selected month; page reads do not generate menus or contact providers. Controls use the application's existing login, CSRF and no-store protections.

## Print a shopping checklist

Open **Monthly meals & shops → Supermarket checklist & print**. Choose a shopping date and untick anything you already have, then select **Print shopping checklist**. The printer receives one receipt with a tick box for each selected ingredient and its shopping quantity. Local supplier lists have their own print button. A copyable list is available on the same page.

The calendar shows lunch on the date it is planned for, using the previous dinner’s lunch option where present, including across month boundaries. A saved lunch override appears instead. If nobody needs lunch or there is no saved lunch plan, the card says so. A calendar entry is a plan, not confirmation that leftovers are available.

## Local suppliers and meal attendance

Baker, butcher, greengrocer, fishmonger and local shop ingredients stay off the supermarket checklist. Open the local supplier’s dated list from **Shopping lists** to review, print or copy it. Edit the category’s supplier under **Shopping days & shops** if you prefer to buy it elsewhere. The app adds a task for each scheduled specialist shop visit, with a link to the list. Existing unfinished weekday shop tasks are reconciled to the weekend when tasks refresh; completed tasks are kept. Automated shop tasks appear as due only on their scheduled weekend day.

With household profiles configured, expand **Who’s eating?** on a date to skip individual breakfasts, lunches or dinners. Mark all three for a full day away. Breakfast and dinner portions follow their own headcounts; lunch counts adjust extras reserved with the previous dinner where the recipe provides them. A home meal is paused when nobody needs it. Saved dinner recipes remain available if attendance changes again, and household dietary restrictions still apply. The planner does not invent a standalone lunch when there is no suitable previous dinner.
