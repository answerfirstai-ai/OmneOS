"""Allow `python -m core` to run the OMNE command."""

from core.api.main import main

if __name__ == "__main__":
    raise SystemExit(main())
