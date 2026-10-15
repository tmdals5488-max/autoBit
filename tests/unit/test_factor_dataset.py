from dataclasses import replace
import pandas as pd
import pytest
from autobit.data.factor_dataset import Observation, CalendarSnapshot, ScheduledEvent, FactorDataset

T = pd.Timestamp('2025-01-01T00:00:00Z')


def obs(value=False, **kwargs):
    return replace(Observation(T, T, T + pd.Timedelta(days=1), value, 'fixture-proof'), **kwargs)


def dataset(**kwargs):
    return FactorDataset(macro={name: [obs()] for name in ('vix','us2y','usd','nasdaq')}, **kwargs)


def test_release_time_expiry_and_no_future_backfill():
    late = obs(True, available_at=T + pd.Timedelta(hours=6))
    data = FactorDataset(macro={name: [late] for name in ('vix','us2y','usd','nasdaq')})
    assert data.at(T + pd.Timedelta(hours=4)).macro == (None,)*4
    assert data.at(T + pd.Timedelta(hours=6)).macro == (True,)*4
    assert data.at(T + pd.Timedelta(days=1)).macro == (None,)*4


def test_invalid_new_record_does_not_fallback_to_old_valid_value():
    invalid = obs(None, observed_at=T+pd.Timedelta(hours=4), available_at=T+pd.Timedelta(hours=4))
    data = FactorDataset(macro={name: [obs(),invalid] for name in ('vix','us2y','usd','nasdaq')})
    assert data.at(T+pd.Timedelta(hours=5)).macro == (None,)*4


@pytest.mark.parametrize('change', [{'available_at': T-pd.Timedelta(seconds=1)},
    {'observed_at': pd.Timestamp('2025-01-01')}, {'evidence': ''}, {'valid_until': T}])
def test_unprovable_timing_rejected(change):
    with pytest.raises(ValueError):
        dataset(funding=[obs(0.1, **change)])


def funding():
    start = T-pd.Timedelta(days=90)
    return [Observation(t,t,t+pd.Timedelta(hours=8), float(i), 'synthetic')
            for i,t in enumerate(pd.date_range(start,T,freq='8h'))]


def test_full_90_day_history_and_strict_rank():
    rows = funding()
    assert dataset(funding=rows).at(T).funding_percentile == 100
    assert dataset(funding=rows[1:]).at(T).funding_percentile is None
    assert dataset(funding=rows[:40]+rows[41:]).at(T).funding_percentile is None
    assert dataset(funding=[replace(r,value=1.) for r in rows]).at(T).funding_percentile == 0
    assert dataset(funding=rows).at(T+pd.Timedelta(hours=8)).funding_percentile is None


def test_late_funding_and_future_mutation_do_not_leak():
    rows = funding()
    future = replace(rows[-1], available_at=T+pd.Timedelta(hours=1))
    data = dataset(funding=rows[:-1]+[future])
    assert data.at(T).funding_percentile is None
    assert data.at(T+pd.Timedelta(hours=1)).funding_percentile == 100
    before = dataset(funding=rows).at(T-pd.Timedelta(hours=1))
    assert data.at(T-pd.Timedelta(hours=1)) == before


def calendar(events=(), **kwargs):
    return replace(CalendarSnapshot(T, T-pd.Timedelta(days=1), T+pd.Timedelta(days=2),
        tuple(events), 'complete-calendar-fixture'), **kwargs)


@pytest.mark.parametrize('kind', ['FOMC','CPI','NFP'])
def test_event_boundaries_and_known_calendar(kind):
    event = ScheduledEvent(kind,T+pd.Timedelta(hours=8))
    data = dataset(calendars=[calendar([event])])
    for hours,expected in [(5.999,False),(6,True),(8,True),(10,True),(10.001,False)]:
        snapshot = data.at(T+pd.Timedelta(hours=hours))
        assert snapshot.calendar_ready
        assert snapshot.blackout is expected
    assert not data.at(T-pd.Timedelta(seconds=1)).calendar_ready
    assert not data.at(T+pd.Timedelta(days=2)).calendar_ready


def test_calendar_revision_is_asof_not_final_schedule():
    first = calendar([ScheduledEvent('CPI',T+pd.Timedelta(hours=8))])
    revision = calendar([], available_at=T+pd.Timedelta(hours=9))
    data = dataset(calendars=[first,revision])
    assert data.at(T+pd.Timedelta(hours=8)).blackout
    assert not data.at(T+pd.Timedelta(hours=9)).blackout


def test_missing_calendar_is_not_equivalent_to_known_empty_calendar():
    assert not dataset().at(T).calendar_ready
    assert dataset(calendars=[calendar()]).at(T).calendar_ready


def test_duplicate_observations_rejected_and_input_order_immutable():
    with pytest.raises(ValueError):
        dataset(funding=[obs(1.),obs(2.)])
    original = [obs()]
    data = FactorDataset(macro={'vix': original})
    original.clear()
    assert data.at(T).macro[0] is False


def test_build_uses_actual_bar_close_and_is_prefix_stable():
    opens = pd.date_range(T, periods=3, freq='4h')
    later = obs(True, observed_at=T+pd.Timedelta(hours=9), available_at=T+pd.Timedelta(hours=10))
    initial = dataset()
    changed = FactorDataset(macro={name:[obs(),later] for name in ('vix','us2y','usd','nasdaq')})
    before = initial.build(opens)
    after = changed.build(opens)
    assert opens[0] not in after
    assert before[opens[0]+pd.Timedelta(hours=4)] == after[opens[0]+pd.Timedelta(hours=4)]
    assert before[opens[1]+pd.Timedelta(hours=4)] == after[opens[1]+pd.Timedelta(hours=4)]
    assert after[opens[2]+pd.Timedelta(hours=4)].macro == (True,)*4
    with pytest.raises(TypeError):
        after[T] = None


def test_calendar_needs_coverage_on_both_sides_of_blackout():
    data = dataset(calendars=[calendar(coverage_start=T)])
    assert not data.at(T).calendar_ready
    assert data.at(T+pd.Timedelta(hours=2)).calendar_ready


def test_json_loader_requires_publication_and_source_specification(tmp_path):
    import json
    from autobit.data.factor_dataset import load_factor_dataset
    path = tmp_path/'factors.json'
    raw = {'schema':1, 'source_specification':'synthetic-test-only',
           'macro':{},'funding':[],'calendars':[],'funding_interval_hours':8}
    path.write_text(json.dumps(raw))
    assert load_factor_dataset(path).at(T).macro == (None,)*4
    raw['source_specification'] = ''
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load_factor_dataset(path)
