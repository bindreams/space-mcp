"""Shared model factory helpers for tests."""

from __future__ import annotations

from datetime import datetime, timezone

from space.models import (
    BranchPair,
    MergeRequest,
    MRState,
    PatronusCheckConfig,
    PatronusCheckRun,
    PatronusRun,
    PushMode,
    Reviewer,
    ReviewRole,
    ReviewState,
    RunStatus,
    RunType,
    SpaceAccount,
)


def make_account(name: str = "Anna Zhukova", username: str = "azhukova") -> SpaceAccount:
    first, last = (name.split(" ", 1) + [""])[:2]
    return SpaceAccount(id=f"id-{username}", username=username, email=f"{username}@test.com", first_name=first, last_name=last)


def make_dt(year: int = 2026, month: int = 1, day: int = 16, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def make_mr(**overrides) -> MergeRequest:
    defaults = dict(
        id="123456", number=188120, title="Fix authentication bug",
        state=MRState.OPENED, created_at=make_dt(),
        description=None, created_by=make_account(),
        participants=(Reviewer(user=make_account("John Doe", "jdoe"), role=ReviewRole.REVIEWER, state=ReviewState.PENDING),),
        branch_pair=BranchPair(source_branch="azhukova/fix-auth", target_branch="main", repository="ultimate"),
    )
    defaults.update(overrides)
    return MergeRequest(**defaults)


def make_run(**overrides) -> PatronusRun:
    defaults = dict(
        id="cc448634-880e-411f-9ee6-347e9a6087ac", name="Fix auth (dry run)",
        status=RunStatus.SUCCESSFUL, push_mode=PushMode.DRY_RUN,
        branch_pair=BranchPair(source_branch="refs/patronus/safepush/abc", target_branch="master", repository="ultimate"),
        owner=make_account(), started_at=make_dt(hour=8), run_type=RunType.SAFE_PUSH,
        finished_at=make_dt(hour=8, minute=8),
        space_review_url="https://jetbrains.team/p/IJ/reviews/188120/timeline",
    )
    defaults.update(overrides)
    return PatronusRun(**defaults)


def make_check_config(name: str = "Compile All") -> PatronusCheckConfig:
    return PatronusCheckConfig(
        name=name, build_configuration_id=f"id_{name}", build_configuration_name=f"{name} Build",
        build_configuration_url=f"https://tc.example.com/{name}", project_name="Project", attempt_limit=3,
    )


def make_check_run(name: str = "Compile All", status: RunStatus = RunStatus.SUCCESS, attempts=()) -> PatronusCheckRun:
    return PatronusCheckRun(
        id=f"check-{name}", config=make_check_config(name), status=status,
        queued_at=make_dt(hour=8), started_at=make_dt(hour=8, minute=1), finished_at=make_dt(hour=8, minute=5),
        skip_reason=None, attempts=attempts,
    )
