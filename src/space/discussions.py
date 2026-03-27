"""Timeline and discussion fetching for Space merge requests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from .models import (
    CodeDiscussion,
    Comment,
    SpaceAccount,
    SpaceApp,
    SpacePrincipal,
    TimelineEventClass,
    TimelineItem,
    TimelineMessage,
    parse_attachments,
)
from .models.space import _epoch_ms_to_datetime

if TYPE_CHECKING:
    from .client import SpaceClient

_ATTACHMENT_FIELDS = ("attachments(id,details(className,id,filename,sizeBytes,name,width,height))")


async def _resolve_author(msg: dict[str, Any], client: SpaceClient) -> SpacePrincipal:
    """Resolve a Space chat message author to a SpacePrincipal."""
    author_info = msg.get("author", {})
    details = author_info.get("details") or {}
    class_name = details.get("className", "")

    if class_name == "CUserPrincipalDetails":
        user_details = details.get("user", {})
        user_id = user_details.get("id")
        if user_id:
            try:
                return await SpaceAccount.from_id(client, user_id)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404):
                    return SpaceAccount.from_inline(user_details)
                raise
        # User principal without id — resolve by username if available
        username = user_details.get("username")
        if username:
            try:
                return await SpaceAccount.from_username(client, username)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 404):
                    return SpaceAccount.from_inline(user_details)
                raise
        # Last resort: use inline data (may lack email/full name)
        return SpaceAccount.from_inline(user_details)

    if class_name == "CApplicationPrincipalDetails":
        return SpaceApp(app_name=author_info.get("name", "App"))

    # Fallback for unknown principal types
    return SpaceApp(app_name=author_info.get("name", "Unknown"))


async def fetch_discussions(
    client: SpaceClient,
    project: str,
    repository: str,
    review_id: str,
) -> list[TimelineItem]:
    """Get all discussions, comments, and timeline messages on a merge request.

    Returns:
        List of CodeDiscussion and TimelineMessage instances.
    """
    channel_id = await client.get_feed_channel(project, review_id)
    if not channel_id:
        return []

    async with httpx.AsyncClient() as http:
        messages_url = f"{client.base_url}/api/http/chats/messages"
        feed_fields = (
            "messages(id,text,"
            "author(name,details(className,user(id,username,name))),"
            f"time,thread(id),{_ATTACHMENT_FIELDS},"
            "details(className,"
            "codeDiscussion(id,resolved,channel(id),"
            "anchor(filename,line))))"
        )

        # Paginate: fetch all feed messages ----------------------------------------------------------------------------
        all_msgs: list[dict[str, Any]] = []
        start_from: str | None = None
        while True:
            params: dict[str, str] = {
                "channel": f"id:{channel_id}",
                "sorting": "FromOldestToNewest",
                "batchSize": "50",
                "$fields": feed_fields,
            }
            if start_from:
                params["startFromDate"] = start_from
            response = await http.get(messages_url, headers=client._headers(), params=params)
            response.raise_for_status()
            batch = response.json().get("messages", [])
            if not batch:
                break
            all_msgs.extend(batch)
            if len(batch) < 50:
                break
            last_time = batch[-1].get("time")
            if last_time:
                start_from = datetime.fromtimestamp(last_time / 1000, tz=timezone.utc).isoformat()
            else:
                break

        # Process messages ---------------------------------------------------------------------------------------------
        results: list[TimelineItem] = []
        for msg in all_msgs:
            details = msg.get("details") or {}
            code_disc = details.get("codeDiscussion")

            if code_disc:
                results.append(await _fetch_code_discussion(client, http, messages_url, code_disc))
            else:
                text = msg.get("text")
                if not text:
                    continue
                author = await _resolve_author(msg, client)
                created_at = _epoch_ms_to_datetime(msg["time"]) if msg.get("time") else datetime.now(tz=timezone.utc)
                attachments = parse_attachments(msg)

                thread_replies: tuple[Comment, ...] = ()
                thread_id = (msg.get("thread") or {}).get("id")
                if thread_id:
                    thread_replies = await _fetch_thread_replies(client, http, messages_url, thread_id)

                results.append(
                    TimelineMessage(
                        event_class=TimelineEventClass(details.get("className", "Unknown")),
                        text=text,
                        author=author,
                        created_at=created_at,
                        attachments=attachments,
                        thread_replies=thread_replies,
                    )
                )

        return results


async def _fetch_code_discussion(
    client: SpaceClient,
    http: httpx.AsyncClient,
    messages_url: str,
    code_disc: dict[str, Any],
) -> CodeDiscussion:
    """Fetch a code discussion's comment thread."""
    disc_channel_id = (code_disc.get("channel") or {}).get("id")
    anchor = code_disc.get("anchor") or {}

    comments: list[Comment] = []
    if disc_channel_id:
        thread_fields = (
            "messages(id,text,"
            "author(name,details(className,user(id,username,name))),"
            f"time,{_ATTACHMENT_FIELDS})"
        )
        thread_params = {
            "channel": f"id:{disc_channel_id}",
            "sorting": "FromOldestToNewest",
            "batchSize": "50",
            "$fields": thread_fields,
        }
        thread_response = await http.get(
            messages_url,
            headers=client._headers(),
            params=thread_params,
        )
        if thread_response.status_code == 200:
            for thread_msg in thread_response.json().get("messages", []):
                text = thread_msg.get("text")
                if not text:
                    continue
                author = await _resolve_author(thread_msg, client)
                created_at = _epoch_ms_to_datetime(thread_msg["time"]
                                                   ) if thread_msg.get("time") else datetime.now(tz=timezone.utc)
                comments.append(
                    Comment(
                        text=text,
                        author=author,
                        created_at=created_at,
                        attachments=parse_attachments(thread_msg),
                    )
                )

    return CodeDiscussion(
        id=code_disc.get("id", ""),
        file=anchor.get("filename"),
        line=anchor.get("line"),
        resolved=code_disc.get("resolved", False),
        comments=tuple(comments),
        channel_id=code_disc.get("channel", {}).get("id"),
    )


async def _fetch_thread_replies(
    client: SpaceClient,
    http: httpx.AsyncClient,
    messages_url: str,
    thread_id: str,
) -> tuple[Comment, ...]:
    """Fetch replies in a message thread (dry runs, safe merges, etc.)."""
    reply_fields = (
        "messages(id,text,"
        "author(name,details(className,user(id,username,name))),"
        f"time,{_ATTACHMENT_FIELDS})"
    )
    params = {
        "channel": f"id:{thread_id}",
        "sorting": "FromOldestToNewest",
        "batchSize": "50",
        "$fields": reply_fields,
    }
    response = await http.get(
        messages_url,
        headers=client._headers(),
        params=params,
    )
    if response.status_code != 200:
        return ()

    replies: list[Comment] = []
    for msg in response.json().get("messages", []):
        text = msg.get("text")
        if not text:
            continue
        author = await _resolve_author(msg, client)
        created_at = _epoch_ms_to_datetime(msg["time"]) if msg.get("time") else datetime.now(tz=timezone.utc)
        replies.append(Comment(
            text=text,
            author=author,
            created_at=created_at,
            attachments=parse_attachments(msg),
        ))
    return tuple(replies)
