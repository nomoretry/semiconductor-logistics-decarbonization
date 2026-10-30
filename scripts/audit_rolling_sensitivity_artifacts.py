"""Inspect the synthetic trace contents before publishing compressed evidence."""
import gzip
import hashlib
import json
import math
from rolling_inventory.environment import generate
from rolling_inventory.experiment import ROOT, audit, digest, write
from rolling_sensitivity.experiment import variants


def main():
    out=ROOT/'benchmark_results/rolling_sensitivity_development'
    cfg=json.loads((out/'config.json').read_text())
    original=json.loads((ROOT/'rolling_inventory/config.json').read_text())
    tasks=generate(original,'sensitivity',cfg['demand_seeds'])
    if tasks!=json.loads((out/'tasks.json').read_text()):raise ValueError('not_synthetic_tasks')
    by_id={t['id']:t for t in tasks}
    allowed_strings=set(by_id)|{t['profile'] for t in tasks}|{'base_stock','mean','scenario','oracle','uniform','forecast','free'}
    allowed_keys=set('''id variant kind allocation fraction count sampler rows observation
        t public stock backlog arrivals served_old pipeline carbon_remaining history forecast
        periods horizon scenarios forecast_alpha scenario_seed holding terminal_backlog mass lead
        capacity freight emissions carbon_price initial_inventory base_mean carbon_budget
        initial_pipeline action demand filled_new stock_end backlog_end pipeline_end costs
        carbon cost forecast_error planning solver_calls objective dispatch_variables
        continuous_variables window_carbon_budget status mip_gap terminal_credit net_cost
        profile operating_cost fill_rate final_stock final_stock_by_sku final_backlog backlog_unit_periods
        remaining_carbon accounting_effect behavior_effect net_change_vs_zero_value operating_change_vs_zero_value
        decision_seconds max_integer_variables max_continuous_variables'''.split())
    seen_keys=set();counts={'numeric_leaves':0,'string_leaves':0}
    def inspect(x):
        if isinstance(x,dict):
            if not set(x)<=allowed_keys:raise ValueError('unexpected_fields')
            seen_keys.update(x)
            for v in x.values():inspect(v)
        elif isinstance(x,list):
            for v in x:inspect(v)
        elif isinstance(x,str):
            if x not in allowed_strings:raise ValueError('unexpected_text')
            counts['string_leaves']+=1
        elif type(x) in (int,float) and math.isfinite(x):counts['numeric_leaves']+=1
        else:raise ValueError('unexpected_value')
    expected={(t['id'],json.dumps(v,sort_keys=True)) for t in tasks for v in variants(cfg)}
    seen=set();files=[];periods=0
    for path in sorted(out.glob('traces-*.jsonl.gz')):
        raw=gzip.decompress(path.read_bytes());records=[json.loads(x) for x in raw.splitlines()]
        for record in records:
            inspect(record)
            pair=(record['id'],json.dumps(record['variant'],sort_keys=True))
            if pair in seen or pair not in expected:raise ValueError('trajectory_identity')
            seen.add(pair);audit(by_id[record['id']],record['rows']);periods+=len(record['rows'])
        files.append({'path':str(path.relative_to(ROOT)),'compressed_sha256':digest(path),
                      'uncompressed_sha256':hashlib.sha256(raw).hexdigest(),
                      'compressed_bytes':path.stat().st_size,'trajectories':len(records)})
    if seen!=expected:raise ValueError('trajectory_coverage')
    for name in ('outcomes.jsonl.gz','timing.jsonl.gz'):
        path=out/name;raw=gzip.decompress(path.read_bytes());records=[json.loads(x) for x in raw.splitlines()]
        pairs=[]
        for record in records:
            inspect(record);pairs.append((record['id'],json.dumps(record['variant'],sort_keys=True)))
        if len(pairs)!=len(expected) or set(pairs)!=expected:raise ValueError('ledger_coverage')
        files.append({'path':str(path.relative_to(ROOT)),'compressed_sha256':digest(path),
                      'uncompressed_sha256':hashlib.sha256(raw).hexdigest(),
                      'compressed_bytes':path.stat().st_size,'records':len(records)})
    report={'scope':'local_content_inspection_before_public_upload','files':files,
            'distinct_synthetic_paths':len(tasks),'trajectories':len(seen),'period_records':periods,
            **counts,'all_demand_paths_regenerated_from_synthetic_generator':True,
            'every_trajectory_passes_independent_physical_audit':True,
            'all_keys_checked_against_explicit_allowlist':True,'observed_keys':sorted(seen_keys),
            'only_string_values':'synthetic context identifiers and fixed profile/variant/allocation names',
            'arbitrary_text_fields':0,'api_responses_or_credentials_or_corporate_records':0}
    write(ROOT/'data_sources/rolling_sensitivity_artifact_audit.json',report)
    print(json.dumps({'trajectories':len(seen),'period_records':periods,'inspected':True}))


if __name__=='__main__':main()
