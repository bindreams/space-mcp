"""Client mutations: a failure after Space confirmed the change names it; a failure before stays as it is."""

import json

import httpx
import pytest

from space.client import MergeRequestEditError
from space.models import MergeRequest, ReviewRef
from space.models.enums import UnrecognisedApiValue
from space.mutation import Mutation, MutationCompletedError, MutationTarget

from tests.sample_responses import SAMPLE_CREATED_MERGE_REQUEST

_BRANCH = "azhukova/new-feature"


async def _create(space_client):
    return await space_client.create_merge_request("ij", "ultimate", _BRANCH, "master", "New feature")


def _created(**changes) -> dict:
    body = {**SAMPLE_CREATED_MERGE_REQUEST, **changes}
    return {k: v for k, v in body.items() if v is not _DROP}


_DROP = object()


def _raise_assertion(*args, **kwargs):
    raise AssertionError("contract")


class TestCreateUnreadable:

    @pytest.mark.parametrize(
        ("case", "review", "cause_type", "cause_text"),
        [
            pytest.param(
                "strict-state",
                ReviewRef(number=194200),
                UnrecognisedApiValue,
                "MRState: unrecognised value 'NEW_STATE' (strict mode)",
                marks=pytest.mark.raises_unrecognised_api_value,
            ),
            ("missing-id", ReviewRef(number=194200), KeyError, "'id'"),
            (
                "str-number", ReviewRef(id="abc123"), ValueError,
                "merge request 'abc123' in the API response has an invalid number '12'"
            ),
            ("invalid-json", None, json.JSONDecodeError, "Expecting value: line 1 column 1 (char 0)"),
            ("list-body", None, AttributeError, "'list' object has no attribute 'get'"),
            ("profile-500", ReviewRef(number=194200), httpx.HTTPStatusError, "HTTP 500"),
            ("assertion", ReviewRef(number=194200), AssertionError, "contract"),
        ],
    )
    async def test_unreadable_response_names_the_created_mr(
        self, httpx_mock, space_client, monkeypatch, case, review, cause_type, cause_text
    ):
        if case == "strict-state":
            httpx_mock.add_response(method="POST", json=_created(state="NEW_STATE"))
        elif case == "missing-id":
            httpx_mock.add_response(method="POST", json=_created(id=_DROP))
        elif case == "str-number":
            httpx_mock.add_response(method="POST", json=_created(number="12"))
        elif case == "invalid-json":
            httpx_mock.add_response(method="POST", content=b"not json")
        elif case == "list-body":
            httpx_mock.add_response(method="POST", json=[])
        elif case == "profile-500":
            httpx_mock.add_response(method="POST", json=_created(createdBy={"id": "u1"}))
            httpx_mock.add_response(method="GET", status_code=500)
        else:
            httpx_mock.add_response(method="POST", json=_created())
            monkeypatch.setattr(MergeRequest, "from_api", _raise_assertion)

        with pytest.raises(MutationCompletedError) as info:
            await _create(space_client)

        err = info.value
        assert err.mutation is Mutation.MR_CREATED
        assert err.target == MutationTarget("ij", review, repo="ultimate", source_branch=_BRANCH)
        assert type(err.cause) is cause_type
        assert err.__cause__ is err.cause
        subject = f"merge request {review}" if review is not None else "a merge request"
        assert str(err) == f"{subject} was created, but reading it failed: {cause_text}"


class TestCreateFailsBeforeConfirmation:

    @pytest.mark.parametrize("status", [400, 500])
    async def test_error_status_propagates_unwrapped(self, httpx_mock, space_client, status):
        httpx_mock.add_response(method="POST", status_code=status, json={"error": "x"})
        with pytest.raises(httpx.HTTPStatusError):
            await _create(space_client)

    async def test_transport_error_propagates_unwrapped(self, httpx_mock, space_client):
        httpx_mock.add_exception(httpx.ConnectError("down"), method="POST")
        with pytest.raises(httpx.ConnectError):
            await _create(space_client)


class TestEditUnreadable:

    @pytest.mark.parametrize(
        ("case", "cause_type"),
        [
            ("500", httpx.HTTPStatusError),
            pytest.param("strict-state", UnrecognisedApiValue, marks=pytest.mark.raises_unrecognised_api_value),
            ("missing-id", KeyError),
            ("assertion", AssertionError),
        ],
    )
    async def test_refetch_failure_names_the_applied_edit(
        self, httpx_mock, space_client, sample_merge_request, test_accounts, monkeypatch, case, cause_type
    ):
        httpx_mock.add_response(method="PATCH", json={})
        if case == "500":
            httpx_mock.add_response(method="GET", status_code=500)
        elif case == "strict-state":
            httpx_mock.add_response(method="GET", json={**sample_merge_request, "state": "NEW_STATE"})
        elif case == "missing-id":
            httpx_mock.add_response(method="GET", json={k: v for k, v in sample_merge_request.items() if k != "id"})
        else:
            httpx_mock.add_response(method="GET", json=sample_merge_request)
            monkeypatch.setattr(MergeRequest, "from_api", _raise_assertion)

        with pytest.raises(MutationCompletedError) as info:
            await space_client.edit_merge_request("ij", ReviewRef(number=123456), title="T")

        err = info.value
        assert err.mutation is Mutation.MR_EDITED
        assert err.applied == ("title", )
        assert err.target.review == ReviewRef(number=123456)
        assert type(err.cause) is cause_type
        assert err.__cause__ is err.cause
        assert str(err).startswith("edit applied (title) but re-fetching the updated MR failed: ")

    async def test_id_ref_is_kept(self, httpx_mock, space_client):
        httpx_mock.add_response(method="PATCH", json={})
        httpx_mock.add_response(method="GET", status_code=500)
        with pytest.raises(MutationCompletedError) as info:
            await space_client.edit_merge_request("ij", ReviewRef(id="4Xa1b2"), title="T")
        assert info.value.target.review == ReviewRef(id="4Xa1b2")

    async def test_second_patch_non_http_failure_names_applied_field(self, httpx_mock, space_client):

        def boom(request):
            raise RuntimeError("boom")

        httpx_mock.add_response(method="PATCH", json={})
        httpx_mock.add_callback(boom, method="PATCH")
        with pytest.raises(MergeRequestEditError) as info:
            await space_client.edit_merge_request("ij", ReviewRef(number=123456), title="T", description="D")
        assert info.value.applied == ["title"]
        assert isinstance(info.value.cause, RuntimeError)
