def previous_period_label(kind: str, label: str) -> str:
    if kind == "year":
        return str(int(label) - 1)
    if kind == "quarter":
        year_text, quarter_text = label.split("-Q")
        year, quarter = int(year_text), int(quarter_text)
        return f"{year - 1}-Q4" if quarter == 1 else f"{year}-Q{quarter - 1}"
    raise ValueError(f"Unsupported period kind: {kind}")
