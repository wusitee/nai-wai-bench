#!/usr/bin/env python3
"""Run with uv run --extra data python scripts/prepare_frontend.py --help."""

from nwb.frontend_data import main


if __name__ == "__main__":
    raise SystemExit(main())
