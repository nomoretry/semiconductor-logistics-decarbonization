"""Inventory saved research results and check rolling-bundle file integrity.

This is a local checkout check, not a new experiment, training replay or a query
of GitHub CI. Missing artifacts remain failures; they are never regenerated here.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    specs = {
        'api_test': ['complete', 'planned_requests', 'completed_requests'],
        'query_study_development': ['distinct_contexts', 'training_seeds', 'policy_evaluations',
                                    'descriptive_stability_condition'],
        'query_final_v1': ['distinct_contexts', 'training_seeds', 'policy_evaluations',
                           'frozen_final_executed', 'primary_interval_below_zero', 'full_project_complete'],
        'query_components_development': ['distinct_development_contexts', 'training_seeds',
                                         'ppo_training_runs', 'policy_evaluations', 'new_final_test'],
        'rolling_inventory_development': ['distinct_development_contexts', 'rl_trained', 'scope'],
        'rolling_sensitivity_development': ['distinct_demand_paths', 'trajectories', 'learning', 'scope'],
        'rolling_forecast_development': ['calibration_paths', 'distinct_development_paths', 'trajectories',
                                         'period_records', 'learning', 'scope'],
    }
    results = {}
    errors = []
    for name, fields in specs.items():
        path = ROOT / 'benchmark_results' / name / 'summary.json'
        if not path.is_file():
            errors.append('missing_summary:' + name)
            continue
        saved = json.loads(path.read_text())
        results[name] = {'summary_sha256': digest(path), 'saved_results': {k: saved[k] for k in fields}}
    bundle = ROOT / 'benchmark_results/rolling_sensitivity_development'
    manifest = json.loads((bundle / 'manifest.json').read_text())
    checked = 0
    for name, expected in manifest['files'].items():
        if Path(name).name != name:
            errors.append('invalid_manifest_path:' + name)
            continue
        path = bundle / name
        if not path.is_file():
            errors.append('missing_artifact:' + name)
        elif path.is_symlink() or digest(path) != expected:
            errors.append('changed_artifact:' + name)
        else:
            checked += 1
    from rolling_sensitivity.experiment import identity
    if manifest['sources'] != identity():
        errors.append('changed_sensitivity_sources')
    forecast = ROOT / 'benchmark_results/rolling_forecast_development'
    forecast_checked = 0
    forecast_expected = 0
    if not (forecast / 'manifest.json').is_file():
        errors.append('missing_forecast_manifest')
    else:
        fm = json.loads((forecast / 'manifest.json').read_text())
        forecast_expected = len(fm['files'])
        for name, expected in fm['files'].items():
            if Path(name).name != name:
                errors.append('invalid_forecast_path:' + name)
                continue
            path = forecast / name
            if not path.is_file() or path.is_symlink() or digest(path) != expected:
                errors.append('missing_or_changed_forecast_artifact:' + name)
            else:
                forecast_checked += 1
        from rolling_forecast.experiment import identity as forecast_identity
        if fm['sources'] != forecast_identity():
            errors.append('changed_forecast_sources')
    print(json.dumps({
        'scope': 'local_saved_result_inventory_and_file_integrity_only',
        'new_experiments_executed': False,
        'github_ci_checked': False,
        'results': results,
        'sensitivity_artifact_files_verified': checked,
        'sensitivity_artifact_files_expected': len(manifest['files']),
        'forecast_artifact_files_verified': forecast_checked,
        'forecast_artifact_files_expected': forecast_expected,
        'errors': errors,
        'checkout_check_passed': not errors,
    }, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
