#!/usr/bin/env bash
# Installs the optional NLP dependencies needed by app/enrichment/ner.py.
# Run after `pip install -e .` in the prod / dev env where you want NER active.
#
# See docs/architecture/ENRICHMENT-METHODOLOGY.md.
#
# Usage:
#   bash scripts/install_nlp_deps.sh
#
# Idempotent. Safe to re-run.

set -euo pipefail

# Pick the python that owns the active venv; fall back to python3.
PY="${PYTHON:-python3}"

echo "==> Installing spaCy + transitive deps via the [nlp] extra"
"$PY" -m pip install -e ".[nlp]"

echo "==> Downloading spaCy en_core_web_sm model (~15 MB)"
"$PY" -m spacy download en_core_web_sm

echo "==> Verifying NER is available"
"$PY" - <<'PYEOF'
from app.enrichment.ner import is_available, extract_entities

if not is_available():
    raise SystemExit("NER not available after install — model load failed.")

ents = extract_entities("Apple announces new product in Cupertino on 14 June 2026")
print(f"smoke ok — extracted {len(ents)} entities: {[(e.text, e.label) for e in ents]}")
PYEOF

echo "==> Done. The fetcher will stamp payload.entities + ner_model on the next run."
