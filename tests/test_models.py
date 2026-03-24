"""Tests for domain model dataclasses."""

import dataclasses
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from space.models.enums import (
    MRState,
    PushMode,
    ReviewRole,
    ReviewState,
    RunStatus,
    RunType,
    TimelineEventClass,
)


# Enums =====


class TestEnumsMissing:
    """Unknown API values map to UNKNOWN, not raise."""

    def test_mr_state_unknown(self):
        assert MRState("SomeNewState") == MRState.UNKNOWN

    def test_run_status_unknown(self):
        assert RunStatus("SOME_NEW") == RunStatus.UNKNOWN

    def test_timeline_event_class_unknown(self):
        assert TimelineEventClass("NewEventType") == TimelineEventClass.UNKNOWN


class TestEnumsValues:
    """Enum values match API strings exactly."""

    def test_mr_state_values(self):
        assert MRState("Opened") == MRState.OPENED
        assert MRState("Closed") == MRState.CLOSED
        assert MRState("Merged") == MRState.MERGED

    def test_review_role_values(self):
        assert ReviewRole("Author") == ReviewRole.AUTHOR
        assert ReviewRole("Reviewer") == ReviewRole.REVIEWER
        assert ReviewRole("Watcher") == ReviewRole.WATCHER

    def test_review_state_values(self):
        assert ReviewState("Accepted") == ReviewState.ACCEPTED
        assert ReviewState("Rejected") == ReviewState.REJECTED
        assert ReviewState("Resumed") == ReviewState.RESUMED
        assert ReviewState("Pending") == ReviewState.PENDING

    def test_run_status_both_success_variants(self):
        assert RunStatus("SUCCESS") == RunStatus.SUCCESS
        assert RunStatus("SUCCESSFUL") == RunStatus.SUCCESSFUL
        assert RunStatus.SUCCESS != RunStatus.SUCCESSFUL

    def test_run_status_values(self):
        assert RunStatus("RUNNING") == RunStatus.RUNNING
        assert RunStatus("FAILURE") == RunStatus.FAILURE
        assert RunStatus("CANCELLED") == RunStatus.CANCELLED

    def test_push_mode_values(self):
        assert PushMode("DRY_RUN") == PushMode.DRY_RUN
        assert PushMode("MERGE") == PushMode.MERGE

    def test_run_type_values(self):
        assert RunType("SAFE_PUSH") == RunType.SAFE_PUSH

    def test_timeline_event_class_values(self):
        assert TimelineEventClass("MCMessage") == TimelineEventClass.MC_MESSAGE
        assert TimelineEventClass("M2TextItemContent") == TimelineEventClass.M2_TEXT_ITEM
        assert TimelineEventClass("CodeDiscussionAddedFeedEvent") == TimelineEventClass.CODE_DISCUSSION_ADDED


# BranchPair =====


class TestBranchPair:

    def test_from_api_with_dict_repository(self):
        from space.models import BranchPair
        bp = BranchPair.from_api({
            "sourceBranch": "feature/foo",
            "targetBranch": "main",
            "repository": {"name": "ultimate"},
        })
        assert bp.source_branch == "feature/foo"
        assert bp.target_branch == "main"
        assert bp.repository == "ultimate"

    def test_from_api_with_string_repository(self):
        from space.models import BranchPair
        bp = BranchPair.from_api({
            "sourceBranch": "feature/foo",
            "targetBranch": "main",
            "repository": "ultimate",
        })
        assert bp.repository == "ultimate"

    def test_frozen(self):
        from space.models import BranchPair
        bp = BranchPair(source_branch="a", target_branch="b", repository="c")
        with pytest.raises(dataclasses.FrozenInstanceError):
            bp.source_branch = "x"


# SpacePrincipal / SpaceAccount / SpaceApp =====


class TestSpaceApp:

    def test_name_property(self):
        from space.models import SpaceApp
        app = SpaceApp(app_name="Patronus")
        assert app.name == "Patronus"

    def test_frozen(self):
        from space.models import SpaceApp
        app = SpaceApp(app_name="Patronus")
        with pytest.raises(dataclasses.FrozenInstanceError):
            app.app_name = "Other"


class TestSpaceAccount:

    def test_name_property(self):
        from space.models import SpaceAccount
        account = SpaceAccount(
            id="abc", username="jdoe", email="j@test.com",
            first_name="John", last_name="Doe",
        )
        assert account.name == "John Doe"

    def test_name_falls_back_to_username(self):
        from space.models import SpaceAccount
        account = SpaceAccount(
            id="abc", username="jdoe", email="j@test.com",
            first_name="", last_name="",
        )
        assert account.name == "jdoe"

    def test_equality_by_id(self):
        from space.models import SpaceAccount
        a1 = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        a2 = SpaceAccount(id="abc", username="different", email="x@test.com", first_name="X", last_name="Y")
        assert a1 == a2

    def test_inequality_by_id(self):
        from space.models import SpaceAccount
        a1 = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        a2 = SpaceAccount(id="xyz", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        assert a1 != a2

    def test_hash_by_id(self):
        from space.models import SpaceAccount
        a1 = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        a2 = SpaceAccount(id="abc", username="different", email="x@test.com", first_name="X", last_name="Y")
        assert hash(a1) == hash(a2)
        assert len({a1, a2}) == 1

    def test_frozen(self):
        from space.models import SpaceAccount
        a = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        with pytest.raises(dataclasses.FrozenInstanceError):
            a.username = "other"

    async def test_from_id_makes_api_call(self):
        from space.models import SpaceAccount
        SpaceAccount.clear_cache()

        mock_client = MagicMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "abc123",
            "username": "Anna.Zhukova",
            "name": {"firstName": "Anna", "lastName": "Zhukova"},
            "emails": [{"email": "anna@test.com"}],
        }
        mock_client.request = AsyncMock(return_value=mock_response)

        account = await SpaceAccount.from_id(mock_client, "abc123")
        assert account.id == "abc123"
        assert account.username == "Anna.Zhukova"
        assert account.first_name == "Anna"
        assert account.last_name == "Zhukova"
        assert account.email == "anna@test.com"
        assert account.name == "Anna Zhukova"

    async def test_from_id_caches_result(self):
        from space.models import SpaceAccount
        SpaceAccount.clear_cache()

        mock_client = MagicMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "cached1",
            "username": "cached_user",
            "name": {"firstName": "Cached", "lastName": "User"},
            "emails": [{"email": "c@test.com"}],
        }
        mock_client.request = AsyncMock(return_value=mock_response)

        a1 = await SpaceAccount.from_id(mock_client, "cached1")
        a2 = await SpaceAccount.from_id(mock_client, "cached1")
        assert a1 is a2
        mock_client.request.assert_called_once()  # Only one API call

    async def test_from_username_caches_and_cross_populates(self):
        from space.models import SpaceAccount
        SpaceAccount.clear_cache()

        mock_client = MagicMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "cross1",
            "username": "cross_user",
            "name": {"firstName": "Cross", "lastName": "User"},
            "emails": [{"email": "cross@test.com"}],
        }
        mock_client.request = AsyncMock(return_value=mock_response)

        a1 = await SpaceAccount.from_username(mock_client, "cross_user")
        assert a1.id == "cross1"

        # Should be cached by id too
        a2 = await SpaceAccount.from_id(mock_client, "cross1")
        assert a2 is a1
        mock_client.request.assert_called_once()

    async def test_from_id_with_no_emails(self):
        from space.models import SpaceAccount
        SpaceAccount.clear_cache()

        mock_client = MagicMock()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "noemail",
            "username": "noemail_user",
            "name": {"firstName": "No", "lastName": "Email"},
            "emails": [],
        }
        mock_client.request = AsyncMock(return_value=mock_response)

        account = await SpaceAccount.from_id(mock_client, "noemail")
        assert account.email == ""


# Attachment hierarchy =====


class TestAttachments:

    def test_parse_attachments_filters_unfurl(self):
        from space.models import parse_attachments, FileAttachment, ImageAttachment
        msg = {
            "attachments": [
                {
                    "id": "att-1",
                    "details": {
                        "className": "ImageAttachment",
                        "id": "img-001",
                        "name": "screenshot.png",
                        "width": 1920,
                        "height": 1080,
                    },
                },
                {
                    "id": "att-2",
                    "details": {
                        "className": "FileAttachment",
                        "id": "file-001",
                        "filename": "report.txt",
                        "sizeBytes": 4096,
                    },
                },
                {
                    "id": "att-3",
                    "details": {
                        "className": "UnfurlAttachment",
                        "id": "unfurl-001",
                    },
                },
            ],
        }
        atts = parse_attachments(msg)
        assert len(atts) == 2
        assert isinstance(atts[0], ImageAttachment)
        assert atts[0].width == 1920
        assert atts[0].height == 1080
        assert atts[0].name == "screenshot.png"
        assert isinstance(atts[1], FileAttachment)
        assert atts[1].name == "report.txt"
        assert atts[1].size_bytes == 4096

    def test_parse_attachments_empty(self):
        from space.models import parse_attachments
        assert parse_attachments({}) == ()
        assert parse_attachments({"attachments": []}) == ()
        assert parse_attachments({"attachments": None}) == ()

    def test_attachment_download_url(self):
        from space.models import parse_attachments
        msg = {
            "attachments": [
                {
                    "id": "att-1",
                    "details": {
                        "className": "FileAttachment",
                        "id": "file-id-123",
                        "filename": "test.txt",
                        "sizeBytes": 100,
                    },
                },
            ],
        }
        atts = parse_attachments(msg)
        assert atts[0].download_url == "https://jetbrains.team/d/file-id-123"

    def test_attachment_frozen(self):
        from space.models import FileAttachment
        att = FileAttachment(id="a", name="f.txt", size_bytes=100, download_url="http://x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            att.name = "other"


# Patronus models =====


class TestPatronusCheckConfig:

    def test_from_api(self):
        from space.models import PatronusCheckConfig
        config = PatronusCheckConfig.from_api({
            "name": "Compile All",
            "buildConfigurationId": "compile_all_id",
            "buildConfigurationName": "Compile All Build",
            "buildConfigurationUrl": "https://tc.example.com/compile",
            "buildConfigurationProjectName": "Project / Build",
            "attemptLimit": 3,
        })
        assert config.name == "Compile All"
        assert config.build_configuration_id == "compile_all_id"
        assert config.build_configuration_name == "Compile All Build"
        assert config.build_configuration_url == "https://tc.example.com/compile"
        assert config.project_name == "Project / Build"
        assert config.attempt_limit == 3


class TestPatronusCheckRunAttempt:

    def test_from_api_full(self):
        from space.models import PatronusCheckRunAttempt
        attempt = PatronusCheckRunAttempt.from_api({
            "id": "att-1",
            "number": 0,
            "status": "SUCCESS",
            "buildId": "98765",
            "buildUrl": "https://tc.example.com/build/98765",
            "startedAt": "2026-01-15T08:00:06Z",
            "finishedAt": "2026-01-15T08:07:28Z",
            "failedTestsNumber": 0,
            "failedBuildsNumber": 0,
        })
        assert attempt.id == "att-1"
        assert attempt.number == 0
        assert attempt.status == RunStatus.SUCCESS
        assert attempt.build_id == "98765"
        assert attempt.build_url == "https://tc.example.com/build/98765"
        assert attempt.started_at == datetime(2026, 1, 15, 8, 0, 6, tzinfo=timezone.utc)
        assert attempt.finished_at == datetime(2026, 1, 15, 8, 7, 28, tzinfo=timezone.utc)

    def test_from_api_running(self):
        from space.models import PatronusCheckRunAttempt
        attempt = PatronusCheckRunAttempt.from_api({
            "id": "att-2",
            "number": 0,
            "status": "RUNNING",
            "buildId": "98766",
            "buildUrl": "https://tc.example.com/build/98766",
            "startedAt": "2026-01-15T08:00:06Z",
            "finishedAt": None,
            "failedTestsNumber": None,
            "failedBuildsNumber": None,
        })
        assert attempt.finished_at is None
        assert attempt.failed_tests_count is None

    def test_from_api_normalizes_build_id_to_str(self):
        from space.models import PatronusCheckRunAttempt
        attempt = PatronusCheckRunAttempt.from_api({
            "id": "att-3",
            "number": 0,
            "status": "SUCCESS",
            "buildId": 98765,  # int from API
        })
        assert attempt.build_id == "98765"
        assert isinstance(attempt.build_id, str)


class TestFailedTest:

    def test_from_api(self):
        from space.models import FailedTest
        ft = FailedTest.from_api({
            "name": "com.example.FooTest.test something important",
            "url": "https://tc.example.com/test/123",
        })
        assert ft.name == "com.example.FooTest.test something important"
        assert ft.url == "https://tc.example.com/test/123"

    def test_from_api_no_url(self):
        from space.models import FailedTest
        ft = FailedTest.from_api({"name": "test_foo"})
        assert ft.url is None


class TestFailedBuild:

    def test_from_api(self):
        from space.models import FailedBuild
        fb = FailedBuild.from_api({
            "buildId": "98770",
            "buildUrl": "https://tc.example.com/build/98770",
            "buildConfigurationId": "test_Build",
            "buildConfigurationUrl": "https://tc.example.com/buildConfiguration/test_Build",
            "buildConfigurationName": "Unit Tests",
            "fullProjectName": "Project / Tests",
            "isFailedToStart": False,
            "problems": [
                {"details": "Process exited with code 1"},
                {"details": "1 failed test detected"},
            ],
        })
        assert fb.build_id == "98770"
        assert fb.build_configuration_name == "Unit Tests"
        assert fb.is_failed_to_start is False
        assert fb.problems == ("Process exited with code 1", "1 failed test detected")
