from serializer import serialize_account

def test_serialize_account_name():
    assert serialize_account({"id": "1", "name": "Ada", "email": "a@example.com"})["name"] == "Ada"
