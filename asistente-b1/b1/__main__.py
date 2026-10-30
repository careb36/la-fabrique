"""``python -m b1`` — same entry point as the console script."""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
