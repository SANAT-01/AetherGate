from apps.routing.crypto import decrypt_api_key, encrypt_api_key


def test_encrypt_decrypt_round_trips():
    raw = "sk-super-secret-key"
    encrypted = encrypt_api_key(raw)

    assert encrypted != raw
    assert decrypt_api_key(encrypted) == raw
