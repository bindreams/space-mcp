"""SafeMergeStart: the typed body of a confirmed safe-merge request."""

import pytest

from space.models import SafeMergeEvent, SafeMergeStart


class TestAccepts:

    @pytest.mark.parametrize("data", [{}, None], ids=["empty-dict", "empty-body"])
    def test_empty(self, data):
        assert SafeMergeStart.from_api(data) == SafeMergeStart()
        assert SafeMergeStart.from_api(data).events is None

    def test_empty_list_keeps_its_events(self):
        assert SafeMergeStart.from_api([]).events == ()

    def test_dict(self):
        start = SafeMergeStart.from_api({"robotId": "r", "robotUrl": "u", "status": "RUNNING", "jobId": "j"})
        assert start == SafeMergeStart(run_id="r", run_url="u", status="RUNNING", job_id="j", events=None)

    def test_events(self):
        start = SafeMergeStart.from_api([
            {"type": "Progress", "message": "m"},
            {"type": "Other"},
            {"type": "Success", "message": "ok"},
        ])
        assert start.events == (
            SafeMergeEvent("Progress", "m"),
            SafeMergeEvent("Other", None),
            SafeMergeEvent("Success", "ok"),
        )


@pytest.mark.parametrize(
    "data",
    [
        5,
        "started",
        ["x"],
        [{"type": "Error"}],
        [{"type": "Error", "message": 5}],
        [{"type": "Error", "message": None}],
        [{"type": "Progress"}],
        [{"type": "Progress", "message": 5}],
        [{"type": 5}],
        [{"type": "Other", "message": 5}],
        {"status": ["x"]},
        {"robotId": None},
        {"robotId": 5},
        {"robotId": ""},
        {"robotUrl": 1},
        {"jobId": {}},
    ],
)
def test_rejects(data):
    with pytest.raises(ValueError, match="^unexpected safe-merge response: "):
        SafeMergeStart.from_api(data)
