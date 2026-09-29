"""Allow `python -m core` to run the JARVIS command."""

from core.api.main import main

if __name__ == "__main__":
    raise SystemExit(main())
