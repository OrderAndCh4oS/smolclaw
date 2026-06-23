def parse_int_list(value: str) -> list[int]:
    """Parse a comma-separated list of integers."""
    if not value:
        return []
    return [int(part) for part in value.split(",")]
