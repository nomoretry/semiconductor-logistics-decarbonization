"""Inspect every synthetic trace field before publishing the research archive."""
import json
import math
from pathlib import Path
import re
from rolling_inventory.environment import generate
from rolling_inventory.experiment import ROOT, audit, close, digest
from rolling_forecast.experiment import DEFAULT, identity, load, settings


def numeric(value):
    if isinstance(value, dict):
        for x in value.values():numeric(x)
    elif isinstance(value, list):
        for x in value:numeric(x)
    elif type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('non_numeric_trace_leaf')


def main():
    cfg, physical=settings()
    tasks=generate(physical,'forecast-development',cfg['development_seeds'])
    calibration=generate(physical,'forecast-calibration',cfg['calibration_seeds'])
    close(calibration+tasks,load(DEFAULT/'tasks.json'))
    manifest=load(DEFAULT/'manifest.json')
    if manifest['sources']!=identity():raise ValueError('source_identity')
    for name,sha in manifest['files'].items():
        if Path(name).name!=name or digest(DEFAULT/name)!=sha:raise ValueError('file_hash')
    row_keys={'action','demand','filled_new','stock_end','backlog_end','pipeline_end','emissions',
              'costs','cost','observation','policy_observation_sha256','forecast_used','planning'}
    costs={'freight','carbon','holding','backlog','terminal_backlog'}
    plan={'objective','scenarios','horizon','dispatch_variables','continuous_variables',
          'window_carbon_budget','status','mip_gap'}
    expected={(m,s) for m in ['original_ewma','fast_ewma','seasonal_window'] for s in cfg['sampler_seeds']}
    expected|={('base_stock',0),('clairvoyant',0)}
    trajectories=0;periods=0;files=[]
    for i,task in enumerate(tasks):
        path=DEFAULT/f'traces-{i:02}.jsonl';records=load(path);seen=set()
        for record in records:
            if set(record)!={'id','method','sampler','rows'} or record['id']!=task['id']:
                raise ValueError('trace_metadata')
            pair=record['method'],record['sampler']
            if pair not in expected or pair in seen:raise ValueError('trace_variant')
            seen.add(pair)
            for row in record['rows']:
                if set(row)!=row_keys or set(row['costs'])!=costs or set(row['observation'])!={'arrivals','served_old'}:
                    raise ValueError('trace_fields')
                keys={'solver_calls'} if pair[0]=='base_stock' else plan | ({'solver_calls'} if pair[0]!='clairvoyant' else set())
                if set(row['planning'])!=keys:raise ValueError('planning_fields')
                if not re.fullmatch('[0-9a-f]{64}',row['policy_observation_sha256']):raise ValueError('observation_hash')
                numeric({k:v for k,v in row.items() if k!='policy_observation_sha256'})
                periods+=1
            audit(task,record['rows']);trajectories+=1
        if seen!=expected:raise ValueError('variant_coverage')
        files.append({'path':str(path.relative_to(ROOT)), 'bytes':path.stat().st_size, 'sha256':digest(path)})
    result={'scope':'full_field_inspection_and_independent_physical_audit_of_synthetic_traces',
            'tasks_regenerated':True,'source_and_file_hashes_checked':True,
            'free_text_fields_in_traces':False,'allowed_strings':'regenerated task IDs, fixed method names, SHA256 hex',
            'trajectories':trajectories,'period_records':periods,'files':files}
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
