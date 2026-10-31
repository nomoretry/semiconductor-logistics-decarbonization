PYTHON ?= python
CLI = $(PYTHON) -m semiconductor_logistics

.PHONY: sync test smoke benchmark verify report ci ci-core ci-foundation verify-core verify-final verify-components verify-rolling verify-sensitivity verify-strict-training package-check download-data real-notices decision-audit

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
	$(CLI) coupled-audit --contexts 3 --output artifacts/smoke/coupled
	$(CLI) coupled-audit --verify --output artifacts/smoke/coupled
	$(CLI) notice-facts validate
	$(CLI) notice-facts offline --output artifacts/smoke/notice_facts
	$(CLI) notice-facts api --output artifacts/smoke/notice_facts
	$(CLI) scale-audit --smoke --output artifacts/smoke/decision_scale
	$(PYTHON) -m scripts.smoke_query_budget
	$(CLI) query-bc --smoke-check
	$(CLI) query-ppo --smoke-check
	$(CLI) query-study smoke-check
	$(CLI) query-components smoke-check
	$(CLI) rolling-inventory smoke-check
	$(CLI) rolling-sensitivity smoke-check
	$(CLI) rolling-forecast smoke-check
	$(CLI) rolling-distribution smoke-check

# Full grid includes the external demand analogue; download-data is explicit.
benchmark:
	$(CLI) optimize --project both

verify-core:
	$(CLI) verify-run
	$(CLI) workflow-audit --verify
	$(CLI) score-api --run benchmark_results/api_smoke
	$(CLI) compare-api --run benchmark_results/api_test --repeat-run benchmark_results/api_repeat --output artifacts/comparison_replay
	$(CLI) decision-audit --verify --output benchmark_results/decision_development
	$(PYTHON) -m scripts.verify_real_notice_archive
	$(PYTHON) -m scripts.verify_notice_facts_archive
	$(CLI) coupled-audit --verify --output benchmark_results/coupled_development
	$(CLI) scale-audit --verify --output benchmark_results/decision_scale
	$(CLI) query-budget --verify --output benchmark_results/query_budget_development
	$(PYTHON) -m scripts.diagnose_query_budget --verify
	$(CLI) query-bc --verify --output benchmark_results/query_bc_development
	$(PYTHON) -m scripts.diagnose_query_policy --verify
	$(PYTHON) -m scripts.verify_training_portable

verify-final:
	$(CLI) query-study verify-final

verify: verify-core verify-final

# Byte-identical checkpoint hashes require the original numerical dispatch.
# The default verifier binds those hashes to stored full coefficient arrays.
verify-strict-training:
	$(CLI) query-ppo --verify --output benchmark_results/query_ppo_development
	$(CLI) query-study verify-development

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

verify-components:
	$(CLI) query-components verify

ci-core: test smoke verify package-check

verify-rolling:
	$(CLI) rolling-inventory verify

ci-foundation: test smoke verify-core package-check

verify-sensitivity:
	$(CLI) rolling-sensitivity verify

verify-forecast:
	$(CLI) rolling-forecast verify

verify-distribution:
	$(CLI) rolling-distribution verify

ci: ci-core verify-components verify-rolling verify-sensitivity verify-forecast verify-distribution
