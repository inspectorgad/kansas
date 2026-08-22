import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas.common import CandidatePair  # noqa: E402
from schemas.polls import Poll  # noqa: E402


def make_poll(
    pollster: str,
    marshall: float,
    hamilton: float,
    end: date,
    sample: int | None = 600,
    days: int = 3,
    sponsor: str | None = None,
    partisan: str | None = None,
) -> Poll:
    from datetime import timedelta

    return Poll(
        id=f"{pollster}-{end.isoformat()}",
        pollster=pollster,
        sponsor=sponsor,
        partisan=partisan,
        start_date=end - timedelta(days=days),
        end_date=end,
        sample_size=sample,
        population="LV",
        results=CandidatePair(marshall=marshall, hamilton=hamilton),
    )


@pytest.fixture
def poll_factory():
    return make_poll


@pytest.fixture
def as_of() -> date:
    return date(2026, 8, 22)
