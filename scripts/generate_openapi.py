#!/usr/bin/env python3
"""
Generate OpenAPI specification from the FastAPI application.

Usage:
    cd backend && PYTHONPATH=.:app python3 ../scripts/generate_openapi.py

Output:
    backend/app/openapi.yaml — OpenAPI 3.0 specification
"""

import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.main import app


def generate_openapi():
    """Generate and save OpenAPI specification."""
    openapi_schema = app.openapi()

    # Write as JSON (can be converted to YAML with tools)
    output_path = Path(__file__).parent.parent / "backend" / "app" / "openapi.json"
    output_path.write_text(json.dumps(openapi_schema, indent=2))

    print(f"OpenAPI specification generated: {output_path}")
    print(f"  - Title: {openapi_schema['info']['title']}")
    print(f"  - Version: {openapi_schema['info']['version']}")
    print(f"  - Endpoints: {len(openapi_schema['paths'])}")


if __name__ == "__main__":
    generate_openapi()
