"""Research-only, monotone risk overlay. No core policy or execution ownership."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import math
from numbers import Real

from autobit.risk.breakers import RiskDecision


class Variant(str, Enum):
    A = 'A'
    B = 'B'
    C = 'C'
    D = 'D'


@dataclass(frozen=True, slots=True)
class FactorSnapshot:
    as_of: datetime
    macro: tuple[bool | None, ...]  # VIX, US2Y, broad USD, Nasdaq
    funding_percentile: float | None = None  # [0, 100], not a fraction
    calendar_ready: bool = False
    blackout: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'macro', tuple(self.macro))


@dataclass(frozen=True, slots=True)
class OverlayResult:
    risk: RiskDecision
    score: int | None
    multiplier: float
    entry_blocked: bool


def apply_overlay(original: RiskDecision, variant: Variant,
                  factors: FactorSnapshot | None, *, now: datetime) -> OverlayResult:
    if not isinstance(variant, Variant):
        raise ValueError('variant must be a registered Variant')
    if variant is Variant.A:
        return OverlayResult(original, 0, 1., _blocked(original))
    if not all(_number(v) and v >= 0 for v in (original.risk_rate, original.exposure_cap)):
        raise ValueError('canonical risk must be finite and nonnegative')
    valid = (isinstance(factors, FactorSnapshot) and isinstance(now, datetime) and now.tzinfo is not None
             and now.utcoffset() is not None and factors.as_of == now
             and len(factors.macro) == 4 and all(type(v) is bool for v in factors.macro))
    if valid and variant in (Variant.C, Variant.D):
        valid = _number(factors.funding_percentile) and 0 <= factors.funding_percentile <= 100
    if valid and variant is Variant.D:
        valid = factors.calendar_ready is True and type(factors.blackout) is bool
    if not valid:
        return _restricted(original, None, 0., 'overlay_data_unavailable')
    score = sum(factors.macro)
    if variant in (Variant.C, Variant.D):
        score += 2 if factors.funding_percentile > 95 else int(factors.funding_percentile > 80)
    multiplier = (1., .75, .5, .25, .1)[min(score, 4)]
    if variant is Variant.D and factors.blackout:
        return _restricted(original, score, 0., 'overlay_event_blackout')
    return _restricted(original, score, multiplier,
                       'overlay_risk_reduced' if multiplier < 1 else None)


def _restricted(original, score, multiplier, reason):
    risk = replace(original, risk_rate=original.risk_rate * multiplier,
                   exposure_cap=original.exposure_cap * multiplier,
                   reasons=original.reasons + ((reason,) if reason else ()))
    return OverlayResult(risk, score, multiplier, _blocked(risk))


def _blocked(risk):
    return risk.halted_until is not None or risk.risk_rate <= 0 or risk.exposure_cap <= 0


def _number(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False
