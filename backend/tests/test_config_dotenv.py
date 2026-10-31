"""A .env with keys the backend does not read still starts it."""

from config import Settings


def test_unknown_and_retired_dotenv_keys_are_ignored(tmp_path):
    # The .env is shared with docker compose, and an install upgraded from a
    # version with the voice routes still carries their keys.
    env = tmp_path / ".env"
    env.write_text(
        "VOICE_API_KEY=old-key\nVOICE_COMPANY_ID=\nFABRICA_BUILDS_DIR=/x\n"
        "AUTH_RATE_LIMIT=5/minute\n"
    )
    loaded = Settings(_env_file=env)
    assert loaded.AUTH_RATE_LIMIT == "5/minute"
    assert not hasattr(loaded, "VOICE_API_KEY")
