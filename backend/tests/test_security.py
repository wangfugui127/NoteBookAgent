from datetime import timedelta

from app.core.security import create_token, decode_token, hash_password, verify_password


def test_password_hash_and_token_roundtrip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    token = create_token("user-1", "access", timedelta(minutes=1))
    assert decode_token(token, "access")["sub"] == "user-1"
