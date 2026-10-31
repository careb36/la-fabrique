"""A .env with keys the backend does not read still starts it."""

from config import Settings


def test_unknown_dotenv_keys_are_ignored(tmp_path):
    # The .env is shared with docker compose: FABRICA_BUILDS_DIR is read with
    # os.getenv, never a Settings field, and an upgraded install may carry
    # keys a later version retired.
    env = tmp_path / ".env"
    env.write_text("FABRICA_BUILDS_DIR=/x\nA_RETIRED_KEY=1\nAUTH_RATE_LIMIT=5/minute\n")
    loaded = Settings(_env_file=env)
    assert loaded.AUTH_RATE_LIMIT == "5/minute"
    assert not hasattr(loaded, "A_RETIRED_KEY")
