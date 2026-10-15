"""Point-in-time factor inputs; no download, guessed publication times or backfill.

Macro stress definitions belong to a separately pre-registered source specification.
Funding uses the strict empirical rank against the preceding 90 calendar days,
excluding the current observation. A complete, fixed-cadence history is required.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import MappingProxyType

from autobit.risk.multifactor import FactorSnapshot, _number

MACRO_NAMES = ('vix', 'us2y', 'usd', 'nasdaq')
WINDOW = timedelta(days=90)
BLACKOUT = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class Observation:
    observed_at: datetime
    available_at: datetime
    valid_until: datetime
    value: bool | float | None
    evidence: str


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    kind: str
    scheduled_at: datetime


@dataclass(frozen=True, slots=True)
class CalendarSnapshot:
    available_at: datetime
    coverage_start: datetime
    coverage_end: datetime
    events: tuple[ScheduledEvent, ...]
    evidence: str

    def __post_init__(self):
        object.__setattr__(self, 'events', tuple(self.events))


class _Series:
    def __init__(self, records):
        self.rows = tuple(sorted(records, key=lambda r: r.observed_at))
        for row in self.rows:
            for stamp in (row.observed_at, row.available_at, row.valid_until):
                _aware(stamp)
            if not row.observed_at <= row.available_at < row.valid_until or not row.evidence.strip():
                raise ValueError('invalid publication timing or missing evidence')
        for left, right in zip(self.rows, self.rows[1:]):
            if left.observed_at == right.observed_at or left.available_at >= right.available_at:
                raise ValueError('duplicate/revised or non-monotone publication stream is unsupported')
        self.times = tuple(r.available_at for r in self.rows)

    def index_at(self, now):
        return bisect_right(self.times, now) - 1

    def at(self, now):
        i = self.index_at(now)
        if i < 0 or now >= self.rows[i].valid_until:
            return None
        return self.rows[i]


class FactorDataset:
    def __init__(self, *, macro, funding=(), calendars=(), funding_interval_hours=8):
        if (type(funding_interval_hours) is not int or funding_interval_hours <= 0
                or 2160 % funding_interval_hours):
            raise ValueError('funding interval must divide the 90-day window')
        if set(macro) - set(MACRO_NAMES):
            raise ValueError('unknown macro factor')
        self.macro = MappingProxyType({name: _Series(macro.get(name, ())) for name in MACRO_NAMES})
        self.funding = _Series(funding)
        self.interval = timedelta(hours=funding_interval_hours)
        self.history_count = 2160 // funding_interval_hours
        self.calendars = tuple(sorted(calendars, key=lambda r: r.available_at))
        for row in self.calendars:
            for stamp in (row.available_at, row.coverage_start, row.coverage_end):
                _aware(stamp)
            if row.coverage_start >= row.coverage_end or not row.evidence.strip():
                raise ValueError('invalid calendar coverage/evidence')
            for event in row.events:
                _aware(event.scheduled_at)
                if event.kind not in ('FOMC','CPI','NFP'):
                    raise ValueError('unknown event kind')
                if not row.coverage_start <= event.scheduled_at < row.coverage_end:
                    raise ValueError('event outside declared complete coverage')
        self.calendar_times = tuple(c.available_at for c in self.calendars)
        if len(set(self.calendar_times)) != len(self.calendar_times):
            raise ValueError('ambiguous calendar versions')
        self._percentiles = self._funding_ranks()

    def _funding_ranks(self):
        ranks = []
        rows = self.funding.rows
        n = self.history_count
        for i, row in enumerate(rows):
            history = rows[max(0, i-n):i]
            usable = (len(history) == n and _number(row.value)
                      and history[0].observed_at == row.observed_at - WINDOW
                      and all(_number(r.value) for r in history)
                      and all(b.observed_at-a.observed_at == self.interval
                              for a,b in zip(history, (*history[1:], row))))
            ranks.append(100 * sum(r.value < row.value for r in history) / n if usable else None)
        return tuple(ranks)

    def at(self, now):
        _aware(now)
        macro = tuple(series.at(now) for series in self.macro.values())
        stress = tuple(r.value if r is not None and type(r.value) is bool else None for r in macro)
        funding = self.funding.at(now)
        rank = None
        if funding is not None and now < funding.observed_at + self.interval:
            rank = self._percentiles[self.funding.index_at(now)]
        i = bisect_right(self.calendar_times, now) - 1
        calendar = self.calendars[i] if i >= 0 else None
        ready = (calendar is not None and calendar.coverage_start <= now-BLACKOUT
                 and now+BLACKOUT < calendar.coverage_end)
        blackout = ready and any(abs(now-e.scheduled_at) <= BLACKOUT for e in calendar.events)
        return FactorSnapshot(now, stress, rank, bool(ready), bool(blackout))

    def build(self, bar_open_index):
        """Map exact completed-close timestamps, retaining unavailable snapshots."""
        return MappingProxyType({t + timedelta(hours=4): self.at(t + timedelta(hours=4))
                                 for t in bar_open_index})


def _aware(stamp):
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None or stamp != stamp:
        raise ValueError('timestamps must be finite and timezone-aware')


def load_factor_dataset(path: Path):
    """Read the documented versioned JSON contract; never infer timing from dates."""
    raw = json.loads(path.read_text(encoding='utf-8'))
    if type(raw['schema']) is not int or raw['schema'] != 1 or not raw['source_specification'].strip():
        raise ValueError('schema 1 and a pre-registered source specification are required')
    def timestamp(value):
        stamp = datetime.fromisoformat(value)
        _aware(stamp)
        return stamp.astimezone(timezone.utc)
    def observation(row):
        return Observation(*(timestamp(row[k]) for k in ('observed_at','available_at','valid_until')),
                           row['value'], row['evidence'])
    calendars = [CalendarSnapshot(timestamp(r['available_at']), timestamp(r['coverage_start']),
                 timestamp(r['coverage_end']), tuple(ScheduledEvent(e['kind'],timestamp(e['scheduled_at']))
                 for e in r['events']), r['evidence']) for r in raw['calendars']]
    return FactorDataset(macro={k: [observation(r) for r in v] for k,v in raw['macro'].items()},
                         funding=[observation(r) for r in raw['funding']], calendars=calendars,
                         funding_interval_hours=raw['funding_interval_hours'])
