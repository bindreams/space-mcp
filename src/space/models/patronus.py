"""Patronus domain models: runs, checks, attempts, problems."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from .enums import PushMode, RunStatus, RunType
from .space import BranchPair, SpaceAccount

if TYPE_CHECKING:
    from ..client import SpaceClient


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _parse_iso_required(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# Configuration =====


@dataclass(frozen=True)
class PatronusCheckConfig:
    """Configuration for a single check within a Patronus run."""

    name: str
    build_configuration_id: str
    build_configuration_name: str
    build_configuration_url: str | None
    project_name: str
    attempt_limit: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PatronusCheckConfig:
        return cls(
            name=data.get("name", ""),
            build_configuration_id=data.get("buildConfigurationId", ""),
            build_configuration_name=data.get("buildConfigurationName", ""),
            build_configuration_url=data.get("buildConfigurationUrl"),
            project_name=data.get("buildConfigurationProjectName", ""),
            attempt_limit=data.get("attemptLimit", 1),
        )


# Attempts =====


@dataclass(frozen=True)
class PatronusCheckRunAttempt:
    """One build attempt within a check (Patronus retries failed checks)."""

    id: str
    number: int
    status: RunStatus
    build_id: str | None = None
    build_url: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failed_tests_count: int | None = None
    failed_builds_count: int | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PatronusCheckRunAttempt:
        build_id = data.get("buildId")
        return cls(
            id=data["id"],
            number=data.get("number", 0),
            status=RunStatus(data.get("status", "UNKNOWN")),
            build_id=str(build_id) if build_id is not None else None,
            build_url=data.get("buildUrl"),
            started_at=_parse_iso(data.get("startedAt")),
            finished_at=_parse_iso(data.get("finishedAt")),
            failed_tests_count=data.get("failedTestsNumber"),
            failed_builds_count=data.get("failedBuildsNumber"),
        )


# Failure details =====


@dataclass(frozen=True)
class FailedTest:
    name: str
    url: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> FailedTest:
        return cls(name=data["name"], url=data.get("url"))


@dataclass(frozen=True)
class FailedBuild:
    build_id: str
    build_url: str | None
    build_configuration_id: str
    build_configuration_url: str | None
    build_configuration_name: str
    full_project_name: str
    is_failed_to_start: bool
    problems: tuple[str, ...]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> FailedBuild:
        return cls(
            build_id=str(data.get("buildId", "")),
            build_url=data.get("buildUrl"),
            build_configuration_id=data.get("buildConfigurationId", ""),
            build_configuration_url=data.get("buildConfigurationUrl"),
            build_configuration_name=data.get("buildConfigurationName", ""),
            full_project_name=data.get("fullProjectName", ""),
            is_failed_to_start=data.get("isFailedToStart", False),
            problems=tuple(p.get("details", "") for p in data.get("problems", [])),
        )


@dataclass(frozen=True)
class AttemptDetails(PatronusCheckRunAttempt):
    """Extended attempt info with failed tests and builds."""

    failed_tests: tuple[FailedTest, ...] = ()
    failed_builds: tuple[FailedBuild, ...] = ()

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AttemptDetails:
        build_id = data.get("buildId")
        return cls(
            id=data["id"],
            number=data.get("number", 0),
            status=RunStatus(data.get("status", "UNKNOWN")),
            build_id=str(build_id) if build_id is not None else None,
            build_url=data.get("buildUrl"),
            started_at=_parse_iso(data.get("startedAt")),
            finished_at=_parse_iso(data.get("finishedAt")),
            failed_tests_count=data.get("failedTestsNumber"),
            failed_builds_count=data.get("failedBuildsNumber"),
            failed_tests=tuple(FailedTest.from_api(t) for t in data.get("failedTests", [])),
            failed_builds=tuple(FailedBuild.from_api(b) for b in data.get("failedBuilds", [])),
        )


# Check run =====


@dataclass(frozen=True)
class PatronusCheckRun:
    """One build check execution within a Patronus run."""

    id: str
    config: PatronusCheckConfig
    status: RunStatus
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    skip_reason: str | None
    attempts: tuple[PatronusCheckRunAttempt, ...]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PatronusCheckRun:
        config = PatronusCheckConfig.from_api(data)
        return cls(
            id=data["id"],
            config=config,
            status=RunStatus(data.get("status", "UNKNOWN")),
            queued_at=_parse_iso_required(data["queuedAt"]),
            started_at=_parse_iso(data.get("startedAt")),
            finished_at=_parse_iso(data.get("finishedAt")),
            skip_reason=data.get("skipReason"),
            attempts=tuple(PatronusCheckRunAttempt.from_api(a) for a in data.get("attempts", [])),
        )


# Patronus run =====


@dataclass(frozen=True)
class PatronusRun:
    """A Patronus dry run or safe merge execution."""

    id: str
    name: str
    status: RunStatus
    push_mode: PushMode
    branch_pair: BranchPair
    owner: SpaceAccount
    started_at: datetime
    run_type: RunType
    finished_at: datetime | None = None
    space_review_url: str | None = None
    space_review_key: str | None = None
    cancellation_reason: str | None = None

    @classmethod
    async def from_api(cls, data: dict[str, Any], client: SpaceClient) -> PatronusRun:
        """Construct from Patronus run overview response.

        Args:
            data: RobotOverviewDto dict from Patronus API.
            client: SpaceClient for resolving owner to SpaceAccount.
        """
        owner_data = data.get("owner") or {}
        owner_id = owner_data.get("id")
        if not owner_id:
            raise ValueError(f"PatronusRun owner missing 'id': {owner_data}")
        owner = await SpaceAccount.from_id(client, owner_id)

        branch_pair = BranchPair(
            source_branch=data.get("sourceBranch", ""),
            target_branch=data.get("targetBranch", ""),
            repository=data.get("repository", ""),
        )

        return cls(
            id=data["id"],
            name=data.get("name", ""),
            status=RunStatus(data.get("status", "UNKNOWN")),
            push_mode=PushMode(data.get("pushMode", "UNKNOWN")),
            branch_pair=branch_pair,
            owner=owner,
            started_at=_parse_iso_required(data["startDateTime"]),
            run_type=RunType(data.get("type", "UNKNOWN")),
            finished_at=_parse_iso(data.get("finishDateTime")),
            space_review_url=data.get("spaceReviewUrl"),
            space_review_key=data.get("spaceReviewKey"),
            cancellation_reason=data.get("cancellationReason"),
        )


# Problem (assembled, not parsed from single API response) =====


@dataclass(frozen=True)
class Problem:
    """A run-level problem, assembled from /problems + check/attempt data."""

    title: str
    details: str | None = None
    check: PatronusCheckConfig | None = None
    failed_tests: tuple[FailedTest, ...] = ()
    failed_builds: tuple[FailedBuild, ...] = ()
