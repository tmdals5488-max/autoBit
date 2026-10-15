from dataclasses import replace
import pandas as pd
import pytest
from autobit.config import StrategyConfig
from autobit.indicators.trend import compute_trend_indicators
from autobit.risk.multifactor import FactorSnapshot
from tools.research.run_multifactor import common_window, run_matrix


def prices(n=610):
    index = pd.date_range('2020-01-01', periods=n, freq='4h', tz='UTC')
    return pd.DataFrame({'open':100.,'high':101.,'low':99.,'close':100.,'volume':10.},index=index)


def factors(frame):
    return {t+pd.Timedelta(hours=4): FactorSnapshot(t+pd.Timedelta(hours=4),(False,)*4,50.,True,False)
            for t in frame.index}


def test_common_window_respects_warmup_and_keeps_interior_missing_data():
    raw = prices()
    enriched = compute_trend_indicators(raw, StrategyConfig())
    evidence = factors(raw)
    for i in (600,605,609):
        t = raw.index[i]+pd.Timedelta(hours=4)
        evidence[t] = replace(evidence[t], funding_percentile=None)
    common = common_window(enriched,evidence)
    assert common.index[0] == raw.index[601]
    assert common.index[-1] == raw.index[608]
    assert raw.index[605] in common.index
    with pytest.raises(ValueError,match='common'):
        common_window(enriched,{})


def test_matrix_uses_same_dates_and_costs_and_explicit_unavailable_statistics():
    raw = prices()
    result = run_matrix(raw, factors(raw))
    assert len(result['rows']) == 8
    assert {r['variant'] for r in result['rows']} == set('ABCD')
    assert {r['cost'] for r in result['rows']} == {'baseline','stress_20bps'}
    assert len({(r['first_bar'],r['last_bar']) for r in result['rows']}) == 1
    assert all(r['oos'] is None and r['dsr'] is None and r['pbo'] is None for r in result['rows'])
    assert result['recommendation'] == 'NEED MORE DATA'


def test_cli_preserves_inputs_source_and_checksums(monkeypatch, tmp_path):
    import gzip
    import hashlib
    import json
    import sys
    import zipfile
    from pathlib import Path
    import tools.research.run_multifactor as runner
    from autobit.data.quality import QualityReport
    from autobit.cli import SCHEMA_VERSION
    raw = prices()
    data = tmp_path/'processed.csv'
    raw.to_csv(data,index_label='timestamp')
    quality = {name:0 for name in QualityReport.__dataclass_fields__}
    quality['total_bars'] = len(raw)
    (tmp_path/'quality.json').write_text(json.dumps({'schema_version':SCHEMA_VERSION,
        'processed_sha256':hashlib.sha256(data.read_bytes()).hexdigest(),'quality':quality}))
    start = raw.index[0]-pd.Timedelta(days=90)
    end = raw.index[-1]+pd.Timedelta(days=2)
    observation = {'observed_at':start.isoformat(),'available_at':start.isoformat(),
                   'valid_until':end.isoformat(),'value':False,'evidence':'SYNTHETIC TEST ONLY'}
    funding = [{'observed_at':t.isoformat(),'available_at':t.isoformat(),
                'valid_until':(t+pd.Timedelta(hours=8)).isoformat(), 'value':0.01,'evidence':'SYNTHETIC'}
               for t in pd.date_range(start,end,freq='8h')]
    source = tmp_path/'factors.json'
    source.write_text(json.dumps({'schema':1,'source_specification':'SYNTHETIC TEST ONLY',
        'funding_interval_hours':8, 'macro':{n:[observation] for n in ('vix','us2y','usd','nasdaq')},
        'funding':funding,'calendars':[{'available_at':start.isoformat(),'coverage_start':start.isoformat(),
             'coverage_end':end.isoformat(),'events':[],'evidence':'SYNTHETIC'}]}))
    monkeypatch.setattr(runner,'read_provenance',lambda root:{'tracked':['tools/research/run_multifactor.py'],
                                                           'commit':'synthetic-test','dependencies':{}})
    output = tmp_path/'output'
    monkeypatch.setattr(sys,'argv',['run_multifactor','--input',str(data),'--factors',str(source),'--output',str(output)])
    runner.main()
    hashes = json.loads((output/'SHA256SUMS.json').read_text())
    assert all(hashlib.sha256((output/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
    assert gzip.decompress((output/'processed.csv.gz').read_bytes()) == data.read_bytes()
    assert gzip.decompress((output/'factors.json.gz').read_bytes()) == source.read_bytes()
    assert len(json.loads((output/'comparison.json').read_text())['rows']) == 8
    with zipfile.ZipFile(output/'source.zip') as archive:
        assert archive.read('tools/research/run_multifactor.py') == Path(runner.__file__).read_bytes()
    with pytest.raises(FileExistsError):
        runner.main()
