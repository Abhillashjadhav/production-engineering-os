"""Export the committed OpenAPI contract (deterministic: sorted keys)."""

from __future__ import annotations

import json
from pathlib import Path

from pm_evals_api.app import create_app


def main() -> None:
    schema = create_app().openapi()
    out = Path(__file__).resolve().parents[1] / "openapi.json"
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
