# Monthly menus and specialist shopping

Open **Meals → Plan a month of meals**, or **More tools → Monthly meals & shops**. Choose a calendar month, then **Create / complete monthly menu**. The menu includes dinners, their planned next-day lunch extras and optional breakfasts. See [household settings](household-meals.md) for diners, dietary filters, seasonal choices and calendar-aware breakfasts; snacks, drinks and other household needs still need separate allowance.

The month is backed by the same private Sunday-start weekly files used by the daily receipt. Existing meals and eating-out/freezer overrides are retained; missing upcoming weeks/days are filled. New choices retain diet, allergen and weekday-time rules, favour shared components and penalise repeats from earlier weeks in the month. Incompatible future, uneaten recipes are flagged for review and replaced when you complete the monthly menu; past and eaten meals remain recorded. Use each day’s **Change this meal** to edit upcoming, uneaten meals. The edited week feeds the regular receipt and shopping. Generating another overlapping month preserves already planned boundary days.

## Shopping pattern

The default supplier pattern is:

- **Main supermarket shop:** combined store-cupboard and explicitly frozen items for remaining meals.
- **Butcher:** weekly meat requirements, preserving cut/ingredient names and compatible units.
- **Greengrocer:** weekly fresh produce, optionally split by a second midweek shopping day.
- **Supermarket top-up:** fresh essentials and fish by default. Assign these to a local shop, greengrocer or fishmonger where the supplier stocks those items.

Select a shared weekly day to combine stops into an outing. The report counts shopping days, shop stops and supermarket stops separately. These are suggested purchase groupings, not opening-hour checks, optimised journeys or a promise that weekly trips are always sufficient. The first incomplete week can require a catch-up purchase before the normal shopping day. Remaining requirements regroup from the date you view the month; purchases are not automatically tracked or ordered.

Correct individual ingredient categories where automatic classification does not suit the product. Explicit tins/frozen/dried foods and dry staples are separated from fresh products; unknown foods default to fresh essentials. Category corrections persist across future menus. Fresh supplier categories cannot be assigned to the monthly main-shop schedule wholesale. Assign an individual product to cupboard/freezer only after checking its actual packaging, suitability and available freezer space.

Compatible recipe quantities are summed before pack/count rounding. Different cuts, measurement types and incompatible units remain separate. Unmeasured quantities remain visible; no density or weight-per-piece is invented. Items recorded in the pantry remain visible with a stock-check note, since a name or boolean entry does not establish enough stock for a whole month. Amounts use configured household portion factors when enabled; additional guests, drinks, snacks and household essentials need separate allowance.

Bought prep components missing from a recipe's literal ingredients are included as explicit shopping requirements, using the same weekly make/buy decisions as the receipt. Missing amounts remain marked. Homemade component ingredients and original preparation yields are shown separately for manual checking; they are not guessed or automatically scaled. The existing conservative component batching/storage policy still applies.

## Storage and scope

A shopping date is not a shelf-life guarantee. Follow use-by dates, opened-pack instructions and safe chilled/frozen storage; buy closer to use if a product cannot be kept, or freeze suitable portions before their use-by date. Do not treat a monthly menu as permission to refrigerate a month of meat/veg or keep one homemade sauce batch all month. The usual Meals storage/leftovers guide remains available. Guidance checked against:

- [FSA: chilling, freezing and defrosting](https://www.gov.uk/government/publications/how-to-chill-freeze-and-defrost-food-safely/how-to-chill-freeze-and-defrost-food-safely)
- [Best before and use-by dates](https://www.gov.uk/understanding-food-labelling/best-before-and-use-by-dates)

Menu cost is the existing dinner/lunch recipe estimate, excluding breakfast prices and unknown custom recipe costs; it is not live prices or a complete household budget; components, quantities, pack sizes and specialist prices can change the actual total. This page does not send orders, choose a real shop, insert errands, change retailer baskets or replace the existing Tesco review. The daily receipt uses the saved menu without adding a month-long shopping section to the daily paper.

## Local files

Weekly menus remain in `meal_plans/`. Shopping-day, supplier and ingredient-category preferences live in `data/monthly_meals.json`: bounded, validated, locked and atomically written with owner-only permissions. Both are ignored by Git and excluded from the ordinary allowlisted backup; include them in a protected local backup if needed. Invalid saved weekly plans are not overwritten by monthly generation. Generating is local and bounded to the weeks needed for the selected month; page reads do not generate menus or contact providers. Controls use the application's existing login, CSRF and no-store protections.

## Supermarket handoff

In **Monthly meals & shops → Shopping days & shops**, save a preferred online supermarket: Tesco, Sainsbury’s, Asda, Morrisons, Waitrose & Partners or Ocado. Select **Prepare supermarket shopping list** and choose a shopping date. Ingredients from the main supermarket and supermarket top-up stops that day are combined using exact recipe quantities, without rounding twice for packs. The list includes planned breakfasts, eligible dinners, lunch extras and bought components. Check homemade component recipes separately; their yields need a manual check. Pantry items and unmeasured quantities start unticked. Untick items bought elsewhere or already in stock.

All six retailers work with a copyable list and product searches. For Waitrose, use **Multi-search**; where available, Sainsbury’s **SmartLists** can turn the text into product suggestions. The local app does not see your retailer account, trolley, availability, prices or order.

To enable the optional basket review, request Samsung Food/Whisk Graph API access and set the server environment variable `SAMSUNG_FOOD_SERVER_TOKEN` for the process running Receipt Control, then restart. The token must be authorised for list transfers. Keep it on the server and out of version control. The provider documents Tesco, Sainsbury’s and Ocado integration; live availability depends on the provider, retailer and location. Asda, Morrisons and Waitrose use the local copy/search route.

When you explicitly create a basket review, the app sends only selected ingredient lines and quantities plus the chosen retailer and UK language/region. The response is a Samsung Food link. Review pack sizes, missing items, product labels and substitutions there before transferring products to the retailer, then check the retailer basket and place the order yourself. No supermarket login or payment is handled by Receipt Control. A missing token or unavailable service leaves the local list usable.

- [Samsung Food/Whisk list transfer documentation](https://docs.whisk.com/shopping-list-mobile-api/overview)
- [Documented integrated retailers](https://docs.whisk.com/resources/supported-retailers)
- [Waitrose Multi-search](https://www.waitrose.com/ecom/help-information/shopping-with-waitrose/shop-online)
- [Sainsbury’s SmartLists](https://corporate.sainsburys.co.uk/news/press-releases/sainsbury-s-launches-smartlists-a-new-ai-powered-way-to-shop/)

## Local suppliers and meal attendance

Butcher, greengrocer, fishmonger and local shop ingredients stay out of the online supermarket basket. Open the local supplier’s dated list from **Shopping lists** to review and copy it. Edit the category’s supplier under **Shopping days & shops** if you prefer to buy it elsewhere. The app adds a task for each scheduled butcher and greengrocer visit, with a link to the list. Rebuilding the month or changing the schedule reconciles pending tasks and keeps completed ones.

With household profiles configured, expand **Who’s eating?** on a date to skip individual breakfasts, lunches or dinners. Mark all three for a full day away. Breakfast and dinner portions follow their own headcounts; lunch counts adjust extras reserved with the previous dinner where the recipe provides them. A home meal is paused when nobody needs it. Saved dinner recipes remain available if attendance changes again, and household dietary restrictions still apply. The planner does not invent a standalone lunch when there is no suitable previous dinner.
