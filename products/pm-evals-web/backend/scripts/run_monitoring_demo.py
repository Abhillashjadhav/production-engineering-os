"""Run the planted production-monitoring scenario and print its evidence."""

from __future__ import annotations

import json

from pm_evals_monitoring import build_demo_overview


def main() -> None:
    overview = build_demo_overview()
    print(json.dumps(overview.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
