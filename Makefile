PYTHON ?= python
CLI = $(PYTHON) -m semiconductor_logistics

.PHONY: sync test smoke benchmark verify report ci package-check download-data real-notices decision-audit

sync:
	$(PYTHON) -m pip install -c constraints.txt -e '.[dev]'

test:
	$(PYTHON) -m unittest discover -s tests -v

# Small numerical/tool replay plus an API estimate; no credentials or downloads.
# Results have their own directory so archived benchmark evidence stays intact.
smoke:
	$(CLI) evaluate --output artifacts/smoke/notices
	$(CLI) verify-run --output artifacts/smoke/notices
	$(CLI) workflow-audit --tasks 3 --output artifacts/smoke/workflow
	$(CLI) workflow-audit --verify --output artifacts/smoke/workflow
	$(CLI) api --split development --max-calls 3 --output artifacts/smoke/api
	$(CLI) decision-audit --tasks 3 --output artifacts/smoke/decision
	$(CLI) decision-audit --verify --output artifacts/smoke/decision
	$(CLI) real-notices offline --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/smoke/real_notices

# Full grid includes the external demand analogue; download-data is explicit.
benchmark:
	$(CLI) optimize --project both

verify:
	$(CLI) verify-run
	$(CLI) workflow-audit --verify
	$(CLI) score-api --run benchmark_results/api_smoke
	$(CLI) compare-api --run benchmark_results/api_test --repeat-run benchmark_results/api_repeat --output artifacts/comparison_replay
	$(CLI) decision-audit --verify --output benchmark_results/decision_development

report:
	$(CLI) report

package-check:
	$(PYTHON) scripts/check_package.py

download-data:
	$(CLI) download-data

real-notices:
	$(CLI) real-notices offline --dataset benchmarks/real_notices_v1/dataset.json --output artifacts/real_notices

decision-audit:
	$(CLI) decision-audit --tasks 200 --output artifacts/decision_audit

ci: test smoke verify package-check
