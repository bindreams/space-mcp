"""The completed-mutation error: what took effect, and what to inspect."""

import pytest

from space.models import ReviewRef
from space.mutation import Mutation, MutationCompletedError, MutationTarget, created_review_ref


class TestCreatedReviewRef:

    def test_positive_number_wins(self):
        assert created_review_ref({"number": 194200, "id": "abc"}) == ReviewRef(number=194200)

    @pytest.mark.parametrize("number", [0, None, -1, True, "12"], ids=["zero", "null", "negative", "bool", "str"])
    def test_unusable_number_falls_back_to_the_id(self, number):
        assert created_review_ref({"number": number, "id": "abc"}) == ReviewRef(id="abc")

    def test_missing_number_falls_back_to_the_id(self):
        assert created_review_ref({"id": "abc"}) == ReviewRef(id="abc")

    @pytest.mark.parametrize("data", [{"id": ""}, {"id": 5}, {}, {"number": 0}], ids=["empty", "int", "none", "zero"])
    def test_no_usable_identifier(self, data):
        assert created_review_ref(data) is None

    @pytest.mark.parametrize("data", [[], "x", None], ids=["list", "str", "none"])
    def test_non_dict_body(self, data):
        assert created_review_ref(data) is None


class TestMessage:

    @pytest.mark.parametrize(
        ("review", "expected"),
        [
            (ReviewRef(number=194200), "merge request #194200 was created, but reading it failed: 'id'"),
            (ReviewRef(id="abc"), "merge request id:abc was created, but reading it failed: 'id'"),
            (None, "a merge request was created, but reading it failed: 'id'"),
        ],
        ids=["number", "id", "no-ref"],
    )
    def test_created(self, review, expected):
        err = MutationCompletedError(Mutation.MR_CREATED, MutationTarget("ij", review), KeyError("id"))
        assert str(err) == expected
        assert err.args == (expected, )

    def test_edited_names_the_applied_fields(self):
        err = MutationCompletedError(
            Mutation.MR_EDITED,
            MutationTarget("ij", ReviewRef(number=42)),
            RuntimeError("boom"),
            applied=["title", "description"]
        )
        assert str(err) == "edit applied (title, description) but re-fetching the updated MR failed: boom"
        assert err.applied == ("title", "description")

    @pytest.mark.parametrize(
        ("mutation", "expected"),
        [
            (Mutation.COMMENT_POSTED, "comment posted on merge request #42, but reading the response failed: boom"),
            (
                Mutation.DISCUSSION_CREATED,
                "code discussion created on merge request #42, but reading the response failed: boom"
            ),
            (
                Mutation.SAFE_MERGE_ACCEPTED,
                "Space accepted the safe-merge request for merge request #42, but reading the response failed: boom"
            ),
        ],
        ids=["comment", "discussion", "safe-merge"],
    )
    def test_review_mutations(self, mutation, expected):
        assert str(MutationCompletedError(mutation, MutationTarget("ij", ReviewRef(number=42)), ValueError("boom"))) \
            == expected

    def test_run_started(self):
        err = MutationCompletedError(Mutation.RUN_STARTED, MutationTarget("ij", run_id="r-1"), ValueError("boom"))
        assert str(err) == "run r-1 was started, but watching it failed: boom"

    def test_cause_is_described_on_one_line(self):
        err = MutationCompletedError(
            Mutation.MR_CREATED, MutationTarget("ij", ReviewRef(number=1)), ValueError("line one\nline two.")
        )
        assert str(err).endswith("reading it failed: line one line two")

    def test_cause_is_chained(self):
        cause = KeyError("id")
        try:
            raise MutationCompletedError(Mutation.MR_CREATED, MutationTarget("ij"), cause) from cause
        except MutationCompletedError as err:
            assert err.cause is cause
            assert err.__cause__ is cause
