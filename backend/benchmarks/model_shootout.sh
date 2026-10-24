#!/bin/zsh
# Compare NER model combinations on the same corpus. Results land in benchmarks/results/.
# Knowledgator GLiNER lost and is no longer installed: fetch it with scripts/download_models.py --candidates first.
cd "$(dirname "$0")/.."
CASES=${1:-3}
PY=.venv/bin/python
run() { echo "== $1"; $PY benchmarks/run_text_benchmark.py --cases $CASES --show 0 --json benchmarks/results/$1.json "${@:2}" 2>&1 | grep -E "REDACTION RECALL|PRECISION|F1|hard-negative|pages/s"; }
run rules_only --no-ml
run trf_nvidia --spacy en_core_web_trf --gliner nvidia-gliner-pii
run trf_knowledgator --spacy en_core_web_trf --gliner knowledgator-gliner-pii-base
run lg_nvidia --spacy en_core_web_lg --gliner nvidia-gliner-pii
run lg_knowledgator --spacy en_core_web_lg --gliner knowledgator-gliner-pii-base
run nvidia_only --no-spacy --gliner nvidia-gliner-pii
run trf_only --no-gliner --spacy en_core_web_trf
