"""Use counted chicken cuts from the same shop without guessing meat yields."""

from math import ceil

from meals.ingredients import number, parse


def combine_cuts(rows):
    cuts = {"chicken breast": 0, "chicken thigh": 0}
    eligible = []
    for index, row in enumerate(rows):
        parsed = parse(row["line"])
        if parsed and parsed[1] == "count" and parsed[2] in cuts:
            count, _, cut, _ = parsed
            if count > 0 and count.denominator == 1:
                cuts[cut] += int(count)
                eligible.append((index, int(count), cut))

    breasts, thighs = cuts.values()
    # Each bird must supply at least two planned cuts. Fill pairs first, and
    # combine the last single breast and thigh when both are needed.
    birds = max(breasts // 2, thighs // 2, min((breasts + 1) // 2, (thighs + 1) // 2))
    if not birds:
        return rows

    replacements = {}
    capacity = dict.fromkeys(cuts, 2 * birds)
    for index, count, cut in sorted(eligible, key=lambda item: rows[item[0]]["day"]):
        used = min(capacity[cut], count)
        if used:
            replacements[index] = (cut, used, count - used)
            capacity[cut] -= used

    result = []
    first = True
    for index, row in enumerate(rows):
        replacement = replacements.get(index)
        if not replacement:
            result.append(row)
            continue
        cut, used, remaining = replacement
        result.append(dict(
            row,
            line=f"{birds} whole chicken" if first else "",
            shopping_key="whole chicken",
            use_line=f"{used} {cut}{'s' if used > 1 else ''} from the whole chicken",
        ))
        first = False
        if remaining:
            result.append(dict(row, line=f"{remaining} {cut}"))
    return result


def size_guide(lines):
    """Suggest a bird size for weighed cuts, without replacing the cut weights."""
    # Rounded planning assumptions for raw, boneless cuts from a dressed bird.
    # Sources and limitations are recorded in docs/monthly-meals.md.
    yields = {"chicken breast": 18, "chicken thigh": 10}
    weights = dict.fromkeys(yields, 0)
    for line in lines:
        parsed = parse(line)
        if parsed and parsed[1] == "g" and parsed[2] in weights and parsed[0] > 0:
            weights[parsed[2]] += parsed[0]
    needs = [f"{number(grams)} g {cut}" for cut, grams in weights.items() if grams]
    if not needs:
        return None
    tenths_kg = ceil(max(grams / yields[cut] for cut, grams in weights.items()))
    return {
        "needs": " + ".join(needs),
        "size": f"{tenths_kg / 10:g} kg",
    }
