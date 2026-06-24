def parse_csv_row(value: str) -> list[str]:
    """Parse one comma-separated row."""
    return [part.strip() for part in value.split(",") if part.strip()]
