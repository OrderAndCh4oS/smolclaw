from parser import parse_int_list


def test_parse_int_list_accepts_whitespace():
    assert parse_int_list("1, 2, 3") == [1, 2, 3]


def test_parse_int_list_ignores_empty_segments():
    assert parse_int_list("1, , 2") == [1, 2]


def test_parse_int_list_accepts_empty_input():
    assert parse_int_list("") == []
