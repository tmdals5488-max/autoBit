from dataclasses import replace
from pathlib import Path
import pandas as pd
import pytest
from autobit.backtest.engine import BacktestConfig, run_backtest
from autobit.config import CostConfig
from autobit.risk.multifactor import FactorSnapshot, Variant


def frame(name='entry_next_open.csv'):
    return pd.read_csv(Path(__file__).parents[1] / 'fixtures' / name,
                       parse_dates=['timestamp'], index_col='timestamp')


def snapshots(data, macro=(False,)*4, blackout_from=None):
    return {t + pd.Timedelta(hours=4): FactorSnapshot(t + pd.Timedelta(hours=4), macro, 50., True,
            blackout_from is not None and t >= blackout_from) for t in data.index}


def test_default_and_explicit_a_identical_and_b_missing_blocks():
    data = frame()
    baseline = run_backtest(data)
    assert run_backtest(data, research_factors=snapshots(data)) == baseline
    assert run_backtest(data, replace(BacktestConfig(), overlay_variant=Variant.B)).orders == ()
    assert run_backtest(data, replace(BacktestConfig(), overlay_variant=Variant.B),
                        research_factors=snapshots(data)) == baseline


def test_overlay_reduces_actual_next_open_fill():
    data = frame()
    base = BacktestConfig(costs=CostConfig(0.,0.))
    original = run_backtest(data, base)
    reduced = run_backtest(data, replace(base, overlay_variant=Variant.B),
                          research_factors=snapshots(data, macro=(True,True,False,False)))
    before = next(o for o in original.orders if o.side == 'BUY' and o.status == 'COMPLETED')
    after = next(o for o in reduced.orders if o.side == 'BUY' and o.status == 'COMPLETED')
    assert after.filled_quantity == pytest.approx(before.filled_quantity * .5)
    assert after.fill_time == before.fill_time


@pytest.mark.parametrize('name', ['entry_next_open.csv','gap_stop.csv','trailing_activation.csv','old_stop_precedence.csv'])
def test_blackout_after_entry_preserves_position_exit(name):
    data = frame(name)
    baseline = run_backtest(data)
    evidence = snapshots(data, blackout_from=pd.Timestamp('2025-01-05T04:00:00Z'))
    actual = run_backtest(data, replace(BacktestConfig(), overlay_variant=Variant.D), research_factors=evidence)
    assert actual.trades == baseline.trades
    assert actual.orders == baseline.orders


def test_blackout_at_actual_close_time_blocks_entry():
    data = frame()
    evidence = snapshots(data)
    decision_time = pd.Timestamp('2025-01-05T04:00:00Z')
    evidence[decision_time] = replace(evidence[decision_time], blackout=True)
    actual = run_backtest(data, replace(BacktestConfig(), overlay_variant=Variant.D), research_factors=evidence)
    assert actual.orders == ()
