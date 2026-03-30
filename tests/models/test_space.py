"""Tests for Space domain model dataclasses."""

import dataclasses
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from space.models import BranchPair, FileAttachment, ImageAttachment, MergeRequest, Reviewer, ReviewRole, ReviewState, SpaceAccount, SpaceApp, parse_attachments
from tests.factories import make_account, make_mr

# BranchPair ===========================================================================================================


class TestBranchPair:

    def test_from_api_with_dict_repository(self):
        bp = BranchPair.from_api({
            "sourceBranch": "feature/foo",
            "targetBranch": "main",
            "repository": {"name": "ultimate"},
        })
        assert bp.source_branch == "feature/foo"
        assert bp.target_branch == "main"
        assert bp.repository == "ultimate"

    def test_from_api_with_string_repository(self):
        bp = BranchPair.from_api({
            "sourceBranch": "feature/foo",
            "targetBranch": "main",
            "repository": "ultimate",
        })
        assert bp.repository == "ultimate"

    def test_frozen(self):
        bp = BranchPair(source_branch="a", target_branch="b", repository="c")
        with pytest.raises(dataclasses.FrozenInstanceError):
            bp.source_branch = "x"

    def test_dump(self):
        bp = BranchPair(source_branch="feature/foo", target_branch="main", repository="ultimate")
        d = bp.dump()
        assert d == {"source-branch": "feature/foo", "target-branch": "main", "repository": "ultimate"}


# Reviewer dump ========================================================================================================


class TestReviewerDump:

    def test_dump_includes_name_and_state(self):
        reviewer = Reviewer(user=make_account("John Doe", "jdoe"), role=ReviewRole.REVIEWER, state=ReviewState.ACCEPTED)
        d = reviewer.dump()
        assert d == {"name": "@jdoe (John Doe)", "state": "Accepted"}

    def test_dump_pending_state(self):
        reviewer = Reviewer(
            user=make_account("Anna Zhukova", "azhukova"), role=ReviewRole.REVIEWER, state=ReviewState.PENDING
        )
        d = reviewer.dump()
        assert d["state"] == "Pending"


# MergeRequest dump ====================================================================================================


class TestMergeRequestDump:

    def test_dump_basic_fields(self):
        mr = make_mr(number=42, title="Fix bug", description="Desc")
        d = mr.dump()
        assert d["number"] == 42
        assert d["title"] == "Fix bug"
        assert d["description"] == "Desc"
        assert d["state"] == "Opened"

    def test_dump_author_from_created_by(self):
        mr = make_mr(created_by=make_account("Anna Zhukova", "azhukova"))
        d = mr.dump()
        assert d["author"] == "@azhukova (Anna Zhukova)"

    def test_dump_author_unknown_when_none(self):
        mr = make_mr(created_by=None)
        d = mr.dump()
        assert d["author"] == "Unknown"

    def test_dump_includes_branch_pair(self):
        mr = make_mr(branch_pair=BranchPair("feature", "main", "repo"))
        d = mr.dump()
        assert d["source-branch"] == "feature"
        assert d["target-branch"] == "main"
        assert d["repository"] == "repo"

    def test_dump_no_branch_pair(self):
        mr = make_mr(branch_pair=None)
        d = mr.dump()
        assert "source-branch" not in d

    def test_dump_reviewers_excludes_author(self):
        author_reviewer = Reviewer(user=make_account(), role=ReviewRole.AUTHOR, state=ReviewState.PENDING)
        normal_reviewer = Reviewer(
            user=make_account("John Doe", "jdoe"), role=ReviewRole.REVIEWER, state=ReviewState.ACCEPTED
        )
        mr = make_mr(participants=(author_reviewer, normal_reviewer))
        d = mr.dump()
        assert len(d["reviewers"]) == 1
        assert d["reviewers"][0]["name"] == "@jdoe (John Doe)"

    def test_dump_no_reviewers_when_all_authors(self):
        author_reviewer = Reviewer(user=make_account(), role=ReviewRole.AUTHOR, state=ReviewState.PENDING)
        mr = make_mr(participants=(author_reviewer, ))
        d = mr.dump()
        assert "reviewers" not in d

    def test_dump_description_none_included(self):
        mr = make_mr(description=None)
        d = mr.dump()
        assert "description" in d
        assert d["description"] is None


# SpacePrincipal / SpaceAccount / SpaceApp =============================================================================


class TestSpaceApp:

    def test_name_property(self):
        app = SpaceApp(app_name="Patronus")
        assert app.name == "Patronus"

    def test_str(self):
        app = SpaceApp(app_name="Patronus")
        assert str(app) == "Patronus"

    def test_frozen(self):
        app = SpaceApp(app_name="Patronus")
        with pytest.raises(dataclasses.FrozenInstanceError):
            app.app_name = "Other"


class TestSpaceAccount:

    def test_name_property(self):
        account = SpaceAccount(
            id="abc",
            username="jdoe",
            email="j@test.com",
            first_name="John",
            last_name="Doe",
        )
        assert account.name == "John Doe"

    def test_name_falls_back_to_username(self):
        account = SpaceAccount(
            id="abc",
            username="jdoe",
            email="j@test.com",
            first_name="",
            last_name="",
        )
        assert account.name == "jdoe"

    def test_str(self):
        account = SpaceAccount(
            id="abc",
            username="jdoe",
            email="j@test.com",
            first_name="John",
            last_name="Doe",
        )
        assert str(account) == "@jdoe (John Doe)"

    def test_str_falls_back_to_username(self):
        account = SpaceAccount(
            id="abc",
            username="jdoe",
            email="j@test.com",
            first_name="",
            last_name="",
        )
        assert str(account) == "@jdoe (jdoe)"

    def test_str_email_when_no_username(self):
        account = SpaceAccount(
            id="abc",
            username="",
            email="anna.zhukova@jetbrains.com",
            first_name="Anna",
            last_name="Zhukova",
        )
        assert str(account) == "anna.zhukova@jetbrains.com (Anna Zhukova)"

    def test_str_name_only_when_no_username_no_email(self):
        account = SpaceAccount(
            id="abc",
            username="",
            email="",
            first_name="Anna",
            last_name="Zhukova",
        )
        assert str(account) == "Anna Zhukova"

    def test_str_unknown_when_all_empty(self):
        account = SpaceAccount(
            id="abc",
            username="",
            email="",
            first_name="",
            last_name="",
        )
        assert str(account) == "Unknown"

    def test_from_inline_stores_email(self):
        account = SpaceAccount.from_inline({
            "id": "abc",
            "name": "Anna Zhukova",
            "email": "anna.zhukova@jetbrains.com",
        })
        assert account.email == "anna.zhukova@jetbrains.com"

    def test_equality_by_id(self):
        a1 = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        a2 = SpaceAccount(id="abc", username="different", email="x@test.com", first_name="X", last_name="Y")
        assert a1 == a2

    def test_inequality_by_id(self):
        a1 = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        a2 = SpaceAccount(id="xyz", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        assert a1 != a2

    def test_hash_by_id(self):
        a1 = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        a2 = SpaceAccount(id="abc", username="different", email="x@test.com", first_name="X", last_name="Y")
        assert hash(a1) == hash(a2)
        assert len({a1, a2}) == 1

    def test_frozen(self):
        a = SpaceAccount(id="abc", username="jdoe", email="j@test.com", first_name="John", last_name="Doe")
        with pytest.raises(dataclasses.FrozenInstanceError):
            a.username = "other"

    async def test_from_id_makes_api_call(self):
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


# Attachment hierarchy =================================================================================================


class TestAttachments:

    def test_parse_attachments_filters_unfurl(self):
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
        assert parse_attachments({}) == ()
        assert parse_attachments({"attachments": []}) == ()
        assert parse_attachments({"attachments": None}) == ()

    def test_attachment_download_url(self):
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
        att = FileAttachment(id="a", name="f.txt", size_bytes=100, download_url="http://x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            att.name = "other"
