from dataclasses import replace
from datetime import datetime, timezone
import math
import pytest

from autobit.risk.breakers import RiskDecision
from autobit.risk.multifactor import Variant, FactorSnapshot, apply_overlay
from autobit.core.engine import forced_exit_reason

T = datetime(2025, 1, 1, tzinfo=timezone.utc)
BASE = RiskDecision(.02, .7, None, ())


def snap(**kwargs):
    return replace(FactorSnapshot(T, (False,) * 4, 50., True, False), **kwargs)


@pytest.mark.parametrize('score,mult', [(0,1.),(1,.75),(2,.5),(3,.25),(4,.1),(5,.1),(6,.1)])
def test_scores(score, mult):
    factors = snap(macro=tuple(i < min(score,4) for i in range(4)),
                   funding_percentile=99. if score == 6 else 90. if score == 5 else 50.)
    result = apply_overlay(BASE, Variant.C, factors, now=T)
    assert result.score == score
    assert result.multiplier == mult
    assert result.risk.risk_rate == pytest.approx(.02 * mult)
    assert result.risk.exposure_cap == pytest.approx(.7 * mult)


@pytest.mark.parametrize('percentile,score', [(80.,0),(80.0001,1),(95.,1),(95.0001,2)])
def test_strict_funding_boundaries(percentile, score):
    assert apply_overlay(BASE, Variant.C, snap(funding_percentile=percentile), now=T).score == score


@pytest.mark.parametrize('factors', [None, snap(macro=(None,False,False,False)),
    snap(macro=(0,False,False,False)), snap(funding_percentile=math.nan),
    snap(funding_percentile=101.), snap(funding_percentile=True),
    snap(as_of=datetime(2026,1,1,tzinfo=timezone.utc))])
def test_invalid_is_entry_only_fail_closed(factors):
    result = apply_overlay(BASE, Variant.C, factors, now=T)
    assert result.score is None
    assert result.risk.risk_rate == result.risk.exposure_cap == 0
    assert forced_exit_reason(result.risk) is None


def test_modes_only_require_their_own_factors():
    assert apply_overlay(BASE, Variant.A, None, now=T).risk is BASE
    factors = snap(funding_percentile=None, calendar_ready=False)
    assert apply_overlay(BASE, Variant.B, factors, now=T).risk == BASE
    assert apply_overlay(BASE, Variant.C, factors, now=T).risk.risk_rate == 0
    assert apply_overlay(BASE, Variant.D, snap(calendar_ready=False), now=T).risk.risk_rate == 0


@pytest.mark.parametrize('risk', [RiskDecision(0,0,T,('drawdown_halt',)),
    RiskDecision(.0025,.15,None,('recovery',)), RiskDecision(0,.7,None,()),
    RiskDecision(.02,0,None,()), RiskDecision(0,0,None,('system_unhealthy',))])
def test_never_increases_or_erases_existing_restrictions(risk):
    for score in range(5):
        result = apply_overlay(risk, Variant.D, snap(macro=tuple(i < score for i in range(4))), now=T)
        assert 0 <= result.risk.risk_rate <= risk.risk_rate
        assert 0 <= result.risk.exposure_cap <= risk.exposure_cap
        assert result.risk.halted_until == risk.halted_until
        assert set(risk.reasons) <= set(result.risk.reasons)
        assert forced_exit_reason(result.risk) == forced_exit_reason(risk)


def test_event_blocks_entries_without_forced_exit():
    result = apply_overlay(BASE, Variant.D, snap(blackout=True), now=T)
    assert result.risk.risk_rate == result.risk.exposure_cap == 0
    assert 'overlay_event_blackout' in result.risk.reasons
    assert forced_exit_reason(result.risk) is None
    assert apply_overlay(BASE, Variant.C, snap(blackout=True), now=T).risk == BASE


def test_extreme_invalid_percentile_fails_closed():
    result = apply_overlay(BASE, Variant.C, snap(funding_percentile=10**1000), now=T)
    assert result.score is None and result.risk.risk_rate == 0
