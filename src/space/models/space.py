"""Space domain models: accounts, merge requests, timeline items, attachments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, TYPE_CHECKING

import httpx

from .enums import MRState, ReviewRole, ReviewState, TimelineEventClass

if TYPE_CHECKING:
    from ..client import SpaceClient


# Principals =====


class SpacePrincipal(ABC):
    """Base for Space user accounts and applications. Both have a name."""

    @property
    @abstractmethod
    def name(self) -> str: ...


@dataclass(frozen=True)
class SpaceApp(SpacePrincipal):
    """An application principal (e.g., Patronus bot)."""

    app_name: str

    @property
    def name(self) -> str:
        return self.app_name


@dataclass(frozen=True, eq=False)
class SpaceAccount(SpacePrincipal):
    """A Space user account, always fully resolved."""

    id: str
    username: str
    email: str
    first_name: str
    last_name: str

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SpaceAccount) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def name(self) -> str:
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.username

    # Cache =====

    _cache_by_id: ClassVar[dict[str, SpaceAccount]] = {}
    _cache_by_username: ClassVar[dict[str, SpaceAccount]] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Clear all cached accounts. Use in tests and on token rotation."""
        cls._cache_by_id.clear()
        cls._cache_by_username.clear()

    @classmethod
    async def from_id(cls, client: SpaceClient, id: str) -> SpaceAccount:
        """Resolve by profile id. Cached by id (client excluded from key)."""
        if id in cls._cache_by_id:
            return cls._cache_by_id[id]
        resp = await client.request(
            "GET",
            f"/api/http/team-directory/profiles/id:{id}",
            params={"$fields": "id,username,name(firstName,lastName),emails(email)"},
        )
        resp.raise_for_status()
        account = cls._from_profile(resp.json())
        cls._cache_by_id[account.id] = account
        if account.username:
            cls._cache_by_username[account.username] = account
        return account

    @classmethod
    async def from_username(cls, client: SpaceClient, username: str) -> SpaceAccount:
        """Resolve by username. Cached by username (client excluded from key)."""
        if username in cls._cache_by_username:
            return cls._cache_by_username[username]
        resp = await client.request(
            "GET",
            f"/api/http/team-directory/profiles/username:{username}",
            params={"$fields": "id,username,name(firstName,lastName),emails(email)"},
        )
        resp.raise_for_status()
        account = cls._from_profile(resp.json())
        cls._cache_by_id[account.id] = account
        cls._cache_by_username[account.username] = account
        return account

    @classmethod
    def _from_profile(cls, data: dict[str, Any]) -> SpaceAccount:
        """Construct from a Space team-directory profile response."""
        raw_name = data.get("name", {})
        emails = data.get("emails", [])
        return cls(
            id=data["id"],
            username=data["username"],
            email=emails[0]["email"] if emails else "",
            first_name=raw_name.get("firstName", "") if isinstance(raw_name, dict) else "",
            last_name=raw_name.get("lastName", "") if isinstance(raw_name, dict) else "",
        )

    @classmethod
    def from_inline(cls, data: dict[str, Any]) -> SpaceAccount:
        """Construct from inline createdBy/user data (id, name, username).

        Used as fallback when the team directory profile API is not accessible
        (e.g., application tokens without team directory permissions).
        """
        # The "name" field can be a string ("Anna Zhukova") or a dict ({"firstName": ..., "lastName": ...})
        raw_name = data.get("name", "")
        if isinstance(raw_name, dict):
            first_name = raw_name.get("firstName", "")
            last_name = raw_name.get("lastName", "")
        elif isinstance(raw_name, str) and raw_name:
            parts = raw_name.split(None, 1)
            first_name = parts[0] if parts else ""
            last_name = parts[1] if len(parts) > 1 else ""
        else:
            first_name = ""
            last_name = ""

        account = cls(
            id=data.get("id", ""),
            username=data.get("username", ""),
            email="",
            first_name=first_name,
            last_name=last_name,
        )
        if account.id:
            cls._cache_by_id.setdefault(account.id, account)
        if account.username:
            cls._cache_by_username.setdefault(account.username, account)
        return account


# Branch =====


@dataclass(frozen=True)
class BranchPair:
    source_branch: str
    target_branch: str
    repository: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BranchPair:
        repo = data.get("repository")
        if isinstance(repo, dict):
            repo = repo.get("name", "")
        return cls(
            source_branch=data.get("sourceBranch", ""),
            target_branch=data.get("targetBranch", ""),
            repository=repo or "",
        )


# Reviewer =====


@dataclass(frozen=True)
class Reviewer:
    user: SpaceAccount
    role: ReviewRole
    state: ReviewState

    @classmethod
    async def from_api(cls, data: dict[str, Any], client: SpaceClient) -> Reviewer:
        user_data = data.get("user", {})
        try:
            user = await SpaceAccount.from_id(client, user_data["id"])
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 404):
                user = SpaceAccount.from_inline(user_data)
            else:
                raise
        return cls(
            user=user,
            role=ReviewRole(data.get("role", "Unknown")),
            state=ReviewState(data.get("state") or "Pending"),
        )


# Merge request =====


def _epoch_ms_to_datetime(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


@dataclass(frozen=True)
class MergeRequest:
    id: str
    number: int
    title: str
    state: MRState
    created_at: datetime
    description: str | None = None
    created_by: SpaceAccount | None = None
    participants: tuple[Reviewer, ...] = ()
    branch_pairs: tuple[BranchPair, ...] = ()

    @classmethod
    async def from_api(cls, data: dict[str, Any], client: SpaceClient) -> MergeRequest:
        # created_by — fall back to inline data if team directory is inaccessible
        created_by_data = data.get("createdBy")
        created_by = None
        if created_by_data and "id" in created_by_data:
            try:
                created_by = await SpaceAccount.from_id(client, created_by_data["id"])
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404):
                    created_by = SpaceAccount.from_inline(created_by_data)
                else:
                    raise

        # participants — fall back to inline data on 403/404
        participants = tuple([
            await Reviewer.from_api(p, client)
            for p in data.get("participants", [])
        ])

        # branch pairs
        branch_pairs = tuple(
            BranchPair.from_api(bp) for bp in data.get("branchPairs", [])
        )

        return cls(
            id=data["id"],
            number=data.get("number", 0),
            title=data.get("title", ""),
            state=MRState(data.get("state", "Unknown")),
            created_at=_epoch_ms_to_datetime(data["createdAt"]) if "createdAt" in data else datetime.now(tz=timezone.utc),
            description=data.get("description"),
            created_by=created_by,
            participants=participants,
            branch_pairs=branch_pairs,
        )


# Attachments =====


@dataclass(frozen=True)
class Attachment:
    """Base class for file/image/video attachments."""

    id: str
    name: str
    size_bytes: int | None
    download_url: str


@dataclass(frozen=True)
class FileAttachment(Attachment):
    pass


@dataclass(frozen=True)
class ImageAttachment(Attachment):
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class VideoAttachment(Attachment):
    width: int = 0
    height: int = 0


_ATTACHMENT_TYPE_MAP: dict[str, type[Attachment]] = {
    "FileAttachment": FileAttachment,
    "ImageAttachment": ImageAttachment,
    "VideoAttachment": VideoAttachment,
}


def parse_attachments(msg: dict[str, Any]) -> tuple[Attachment, ...]:
    """Parse and filter attachments from a Space chat message.

    Keeps File/Image/Video, skips Unfurl/Deleted.
    """
    result: list[Attachment] = []
    for att in msg.get("attachments") or []:
        details = att.get("details")
        if not details:
            continue
        class_name = details.get("className", "")
        att_cls = _ATTACHMENT_TYPE_MAP.get(class_name)
        if att_cls is None:
            continue
        att_id = details.get("id", att.get("id", ""))
        name = details.get("filename") or details.get("name") or "unnamed"
        size_bytes = details.get("sizeBytes")
        kwargs: dict[str, Any] = {
            "id": att_id,
            "name": name,
            "size_bytes": size_bytes,
            "download_url": f"https://jetbrains.team/d/{att_id}",
        }
        if att_cls in (ImageAttachment, VideoAttachment):
            kwargs["width"] = details.get("width", 0)
            kwargs["height"] = details.get("height", 0)
        result.append(att_cls(**kwargs))
    return tuple(result)


# Timeline items =====


@dataclass(frozen=True)
class Comment:
    text: str
    author: SpacePrincipal
    created_at: datetime
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True)
class CodeDiscussion:
    """A code review comment anchored to a file/line."""

    id: str
    file: str | None
    line: int | None
    resolved: bool
    comments: tuple[Comment, ...] = ()
    channel_id: str | None = None


@dataclass(frozen=True)
class TimelineMessage:
    """A general timeline message (commit, review action, bot notification, etc.)."""

    event_class: TimelineEventClass
    text: str
    author: SpacePrincipal
    created_at: datetime
    attachments: tuple[Attachment, ...] = ()
    thread_replies: tuple[Comment, ...] = ()


TimelineItem = CodeDiscussion | TimelineMessage
