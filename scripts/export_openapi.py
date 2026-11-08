"""Write the OpenAPI schema to docs/openapi.json and web/src/api/openapi.json.
Run from repo root: api/.venv/bin/python scripts/export_openapi.py"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from atlas.http.app import create_app  # noqa: E402

spec = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
for out in (ROOT / "docs" / "openapi.json", ROOT / "web" / "src" / "api" / "openapi.json"):
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(spec)
    print(f"wrote {out.relative_to(ROOT)}")
