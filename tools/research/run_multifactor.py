"""Offline BTC Multi-Factor Risk Overlay v1.2 comparison; never enables trading."""
import argparse
from dataclasses import replace
import gzip
from pathlib import Path
import sys
import zipfile

import pandas as pd
from autobit.backtest.engine import BacktestConfig, run_backtest
from autobit.backtest.benchmark import run_buy_and_hold
from autobit.cli import _read_walk_forward_csv, _load_quality_provenance
from autobit.config import StrategyConfig, CostConfig
from autobit.data.factor_dataset import load_factor_dataset
from autobit.indicators.trend import compute_trend_indicators
from autobit.risk.breakers import RiskDecision
from autobit.risk.multifactor import Variant, apply_overlay
from autobit.validation.models import WalkForwardConfig, WalkForwardRun
from autobit.validation.overfit import deflated_sharpe_probability
from autobit.validation.splits import build_rolling_folds
from autobit.validation.trials import registered_trials, registered_cost_scenarios
from autobit.validation.runner import _request_for_phase, _validate_backtest_result, _stitch_oos
from tools.research.provenance import read_provenance
from tools.research.run_experiment import (
    _bytes, _hash, _write, _metrics, prepare_output, save_cell, validate_source_imports,
)


def common_window(enriched, factors):
    """Trim only outer unavailable coverage; interior missing inputs fail closed.

    Event blackout is valid coverage, not a reason to remove a timestamp.
    The same resulting price index is used for every variant and cost.
    """
    usable = []
    base = RiskDecision(.02,.7,None,())
    for t, row in enriched.iterrows():
        now = t + pd.Timedelta(hours=4)
        result = apply_overlay(base, Variant.D, factors.get(now), now=now)
        usable.append(result.score is not None and bool(row['warmup_complete'])
                      and bool(row['entry_data_valid']))
    covered = enriched.index[usable]
    if len(covered) < 2:
        raise ValueError('no common factor coverage with completed technical warmup')
    return enriched.loc[covered[0]:covered[-1]].copy()


def run_matrix(frame, factors, *, output=None, experiment_hash=None):
    enriched = compute_trend_indicators(frame, StrategyConfig())
    common = common_window(enriched, factors)
    folds = tuple(build_rolling_folds(common.index, WalkForwardConfig()))
    costs = tuple(c for c in registered_cost_scenarios() if c.cost_id in ('baseline','stress_20bps'))
    trial = registered_trials()[0]
    rows = []
    for variant in Variant:
        for cost in costs:
            config = BacktestConfig(costs=CostConfig(cost.fee_rate,cost.slippage_rate),
                                    force_liquidate_at_end=True, overlay_variant=variant)
            full = run_backtest(common, config, research_factors=factors)
            identity = {'experiment':experiment_hash,'variant':variant.value,'cost':cost.cost_id,'config':config}
            if output is not None:
                save_cell(output / f'{variant.value}-{cost.cost_id}-full.json.gz', full, identity)
            runs = []
            for fold in folds:
                for phase in ('TRAIN','OOS'):
                    # Use original pre-common prefix solely for indicator context.
                    request = _request_for_phase(frame,fold=fold,trial=trial,cost=cost,phase=phase)
                    request = replace(request,config=replace(request.config,overlay_variant=variant))
                    result = run_backtest(request.frame,request.config,research_factors=factors)
                    _validate_backtest_result(result,request)
                    runs.append(WalkForwardRun(phase,fold.fold_id,trial.trial_id,cost.cost_id,
                                               'COMPLETED',result,_metrics(result)))
                    if output is not None:
                        save_cell(output / f'{variant.value}-{cost.cost_id}-{fold.fold_id}-{phase}.json.gz',
                                  result,dict(identity,fold=fold.fold_id,phase=phase))
            stitched = _stitch_oos(runs,folds,trial,cost) if folds else None
            if stitched is not None and stitched.status != 'COMPLETE':
                raise ValueError('incomplete OOS evidence')
            if output is not None and stitched is not None:
                _write(output / f'{variant.value}-{cost.cost_id}-oos.json',
                       {'identity':identity,'stitched':stitched})
            audit = [apply_overlay(RiskDecision(.02,.7,None,()),variant,factors.get(t+pd.Timedelta(hours=4)),
                                   now=t+pd.Timedelta(hours=4)) for t in common.index]
            rows.append({'variant':variant.value, 'cost':cost.cost_id,
                         'first_bar':common.index[0], 'last_bar':common.index[-1],
                         'full':_metrics(full), 'oos':stitched.metrics if stitched else None,
                         'positive_folds':sum(r.metrics.expectancy > 0 for r in runs if r.phase=='OOS'),
                         'positive_fold_definition':'OOS expectancy > 0 (existing research convention)',
                         'fold_count':len(folds),
                         'folds':[{'id':r.fold_id,'phase':r.phase,'metrics':r.metrics} for r in runs],
                         'dsr':deflated_sharpe_probability([p.value for p in stitched.returns],4)
                               if stitched and len(folds)>=2 else None,
                         'dsr_scope':'Four fixed variants only; prior research trials not included.',
                         'pbo':None,
                         'pbo_reason':'No overlay-specific purged CPCV re-executions; existing nine-trial PBO is not transferable.',
                         'missing_factor_bars':sum(r.score is None for r in audit),
                         'event_blackout_bars':sum('overlay_event_blackout' in r.risk.reasons for r in audit)})
            print(f'{variant.value} {cost.cost_id}: {len(folds)} folds complete',flush=True)
    return {'research_id':'BTC-Multi-Factor-v1.2','evaluation':'RESEARCH_ONLY',
            'common_start':common.index[0], 'common_end_exclusive':common.index[-1]+pd.Timedelta(hours=4),
            'first_decision_at':common.index[0]+pd.Timedelta(hours=4),
            'period_semantics':'UTC candle-open labels; decisions at open + 4h; interior gaps retained.',
            'split':WalkForwardConfig(), 'rows':rows,
            'buy_and_hold':{c.cost_id:run_buy_and_hold(common,CostConfig(c.fee_rate,c.slippage_rate)) for c in costs},
            'recommendation':'NEED MORE DATA',
            'recommendation_reason':'No automatic adoption: source/threshold review and overlay-specific PBO evidence required.',
            'individual_factors':{name:'NEED MORE DATA' for name in ('VIX','US2Y','USD','Nasdaq','Funding','Event Guard')},
            'individual_factor_reason':'Macro factors have no individual ablation; Funding/Event require OOS review.',
            'prior_exposure':'Historical periods may already have been inspected; not an untouched holdout.'}


def report_markdown(result):
    lines = ['| Variant | CAGR | MDD | Sharpe | Calmar | PF | Trades | Positive Folds |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in result['rows']:
        if row['cost'] != 'baseline':
            continue
        m = row['oos']
        cells = (f'{m.annualized_return:.2%} | {m.max_drawdown:.2%} | {m.sharpe_ratio:.3f} | '
                 f'{m.calmar_ratio:.3f} | {m.profit_factor:.3f} | {m.trade_count}') if m else 'N/A | N/A | N/A | N/A | N/A | N/A'
        lines.append(f"| {row['variant']} | {cells} | {row['positive_folds']}/{row['fold_count']} |")
    lines += ['', 'Table: baseline-cost stitched OOS. N/A is unavailable, never zero evidence.',
              f"Common candle range: {result['common_start']} to {result['common_end_exclusive']} (exclusive).",
              'All full/OOS metrics, cost scenarios, DSR scope, PBO limitations and buy-and-hold are in comparison.json.', '']
    for left,right,label in [('A','B','Macro'),('B','C','Funding'),('C','D','Event Guard')]:
        lines.append(f'{left} vs {right} — {label}:')
        for cost in ('baseline','stress_20bps'):
            pair = [next(r for r in result['rows'] if r['variant']==v and r['cost']==cost) for v in (left,right)]
            a,b = (r['oos'] for r in pair)
            if a is None or b is None:
                lines.append(f'- {cost}: NEED MORE DATA; complete OOS folds unavailable.')
            else:
                lines.append(f'- {cost}: ΔCAGR {b.annualized_return-a.annualized_return:+.2%}, '
                             f'ΔMDD {b.max_drawdown-a.max_drawdown:+.2%}, '
                             f'ΔSharpe {b.sharpe_ratio-a.sharpe_ratio:+.3f}, '
                             f'ΔCalmar {b.calmar_ratio-a.calmar_ratio:+.3f}, '
                             f'ΔPF {b.profit_factor-a.profit_factor:+.3f}.')
        lines.append('')
    lines += ['Recommendation: NEED MORE DATA. PBO comparison and source review are incomplete.',
              'Each individual factor: NEED MORE DATA. No individual macro contribution is inferred.',
              'Baseline archives and production/paper/locked-live defaults remain unchanged.']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--factors',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    validate_source_imports(root)
    inputs = {'processed.csv':args.input.read_bytes(), 'factors.json':args.factors.read_bytes(),
              'quality.json':args.input.with_name('quality.json').read_bytes()}
    data = _read_walk_forward_csv(args.input)
    quality = _load_quality_provenance(args.input,len(data))
    dataset = load_factor_dataset(args.factors)
    if (args.input.read_bytes() != inputs['processed.csv']
            or args.factors.read_bytes() != inputs['factors.json']
            or args.input.with_name('quality.json').read_bytes() != inputs['quality.json']):
        raise ValueError('inputs changed while loading; preserve and investigate')
    factors = dataset.build(data.index)
    # Fail before creating an artifact directory if comparison cannot be run.
    common = common_window(compute_trend_indicators(data,StrategyConfig()),factors)
    provenance = read_provenance(root)
    if Path(__file__).relative_to(root).as_posix() not in provenance['tracked']:
        raise ValueError('commit the research implementation before running the CLI')
    source = {name:_hash((root/name).read_bytes()) for name in provenance['tracked']}
    manifest = {'schema':1,'research_id':'BTC-Multi-Factor-v1.2','provenance':provenance,
                'python':sys.version,'source_files':source,'quality':quality,
                'inputs':{name:_hash(value) for name,value in inputs.items()},
                'common_start':common.index[0],'common_end_exclusive':common.index[-1]+pd.Timedelta(hours=4),
                'strategy':StrategyConfig(),'split':WalkForwardConfig(),
                'configs':{v.value:BacktestConfig(overlay_variant=v,force_liquidate_at_end=True) for v in Variant},
                'costs':[c for c in registered_cost_scenarios() if c.cost_id in ('baseline','stress_20bps')]}
    prepare_output(args.output,manifest)
    with zipfile.ZipFile(args.output/'source.zip','x',zipfile.ZIP_DEFLATED) as archive:
        for name in source:
            payload = (root/name).read_bytes()
            if _hash(payload) != source[name]:
                raise ValueError('source changed while snapshotting; preserve and investigate')
            archive.writestr(name,payload)
    for name,value in inputs.items():
        (args.output/(name+'.gz')).write_bytes(gzip.compress(value,mtime=0))
    try:
        result = run_matrix(data,factors,output=args.output,experiment_hash=_hash(_bytes(manifest)))
        _write(args.output/'comparison.json',result)
        (args.output/'report.md').write_text(report_markdown(result),encoding='utf-8')
        _write(args.output/'SHA256SUMS.json',{
            p.name:_hash(p.read_bytes()) for p in sorted(args.output.iterdir()) if p.is_file()})
    except Exception as error:
        _write(args.output/'failure.json',{'type':type(error).__name__,'message':str(error)})
        raise


if __name__ == '__main__':
    main()
