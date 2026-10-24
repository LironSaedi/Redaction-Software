#!/bin/zsh
# Compare NER model combinations on the independent held-out dev documents (not the synthetic corpus the
# rules were written against). Results land in benchmarks/results/heldout_*.json.
# Knowledgator GLiNER lost and is no longer installed: fetch it with scripts/download_models.py --candidates first.
cd "$(dirname "$0")/.."
PY=.venv/bin/python
run() { echo "== $1"; $PY benchmarks/run_heldout.py --split dev --show 0 --json benchmarks/results/heldout_$1.json "${@:2}" 2>&1 | grep -E "REDACTION RECALL|PRECISION|F1|documents,"; }
run trf_nvidia --spacy en_core_web_trf --gliner nvidia-gliner-pii
run trf_knowledgator --spacy en_core_web_trf --gliner knowledgator-gliner-pii-base
run nvidia_only --no-spacy --gliner nvidia-gliner-pii
run knowledgator_only --no-spacy --gliner knowledgator-gliner-pii-base
run trf_only --no-gliner --spacy en_core_web_trf
run rules_only --no-ml
