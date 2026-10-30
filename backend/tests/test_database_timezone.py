"""database.py: the Postgres session is pinned to UTC.

The models write aware datetimes into ``timestamp`` columns and board
comments carry naive UTC text; only a UTC session keeps the two comparable.
"""

import database


def test_postgres_connections_ask_for_a_utc_session():
    assert database._connect_args("postgresql+psycopg2://u:p@h:5432/db") == {
        "options": "-c timezone=utc"
    }


def test_other_engines_get_no_options():
    assert database._connect_args("sqlite://") == {}


def test_the_backend_engine_is_postgres_so_the_pin_applies():
    assert database.engine.url.drivername == "postgresql+psycopg2"
