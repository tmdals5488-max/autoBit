from pathlib import Path
import pandas as pd

from autobit.risk.multifactor import FactorSnapshot
from tools.research.run_multifactor import run_matrix, report_markdown


def test_real_engine_matrix_with_shared_walk_forward_and_stress_cost(tmp_path):
    # Existing deterministic synthetic fixture, not historical performance evidence.
    frame = pd.read_csv(Path(__file__).parents[1]/'fixtures'/'validation_golden.csv',
                        parse_dates=['timestamp'],index_col='timestamp')
    extension = frame.iloc[:1100].copy()
    extension.index = pd.date_range(frame.index[-1]+pd.Timedelta(hours=4), periods=len(extension), freq='4h')
    frame = pd.concat([frame, extension])
    factors = {t+pd.Timedelta(hours=4): FactorSnapshot(t+pd.Timedelta(hours=4),
               (False,)*4,50.,True,False) for t in frame.index}
    result = run_matrix(frame,factors,output=tmp_path)
    assert len(result['rows']) == 8
    for cost in ('baseline','stress_20bps'):
        rows = [r for r in result['rows'] if r['cost']==cost]
        assert all(r['fold_count'] >= 1 for r in rows)
        # Score zero is precisely the original policy across full and OOS execution.
        assert all(r['full']==rows[0]['full'] and r['oos']==rows[0]['oos'] for r in rows)
        assert rows[0]['full'].trade_count > 0
        assert rows[0]['oos'].trade_count > 0
        assert all(r['pbo'] is None for r in rows)
    assert len(list(tmp_path.glob('*-full.json.gz'))) == 8
    assert len(list(tmp_path.glob('*-oos.json'))) == 8
    report = report_markdown(result)
    assert all(label in report for label in ('A vs B','B vs C','C vs D','NEED MORE DATA'))
