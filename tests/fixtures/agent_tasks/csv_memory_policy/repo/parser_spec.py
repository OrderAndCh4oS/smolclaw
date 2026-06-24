from parser import parse_csv_row


def test_parse_csv_row_strips_surrounding_whitespace():
    assert parse_csv_row("alpha, beta ,gamma") == ["alpha", "beta", "gamma"]


def test_parse_csv_row_preserves_empty_middle_field():
    assert parse_csv_row("alpha,,gamma") == ["alpha", "", "gamma"]


def test_parse_csv_row_preserves_empty_trailing_field():
    assert parse_csv_row("alpha,beta,") == ["alpha", "beta", ""]


def test_parse_csv_row_empty_input_is_one_empty_field():
    assert parse_csv_row("") == [""]
