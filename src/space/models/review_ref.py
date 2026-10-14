from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from .space import MergeRequest

_ASCII_DIGITS = re.compile("[0-9]+")


@dataclass(frozen=True)
class ReviewRef:
    """A merge request reference whose kind is explicit, never guessed from the string."""

    number: int | None = None  # Space's display number
    id: str | None = None  # Space's internal id

    def __post_init__(self) -> None:
        if (self.number is None) == (self.id is None):
            raise ValueError("ReviewRef needs exactly one of number and id")
        if self.number is not None:
            if not isinstance(self.number, int) or isinstance(self.number, bool):
                raise TypeError(f"ReviewRef.number must be an int, got {self.number!r}")
            if self.number <= 0:
                raise ValueError(f"ReviewRef.number must be positive, got {self.number}")
        if self.id is not None:
            if not isinstance(self.id, str):
                raise TypeError(f"ReviewRef.id must be a str, got {self.id!r}")
            if not self.id:
                raise ValueError("ReviewRef.id must be non-empty")

    @classmethod
    def for_mr(cls, mr: MergeRequest) -> ReviewRef:
        """The ref for an MR from the API; a number of 0 means Space sent none."""
        number = mr.number
        if not isinstance(number, int) or isinstance(number, bool):
            raise TypeError(f"merge request {mr.id!r} has a non-int number {number!r}")
        if number < 0:
            raise ValueError(f"merge request {mr.id!r} has a negative number {number}")
        return cls(id=mr.id) if number == 0 else cls(number=number)

    @classmethod
    def by_id(cls, mr: MergeRequest) -> ReviewRef:
        """The internal-id ref for an MR, for requests that need the id whether or not it has a number."""
        return cls(id=mr.id)

    @classmethod
    def parse(cls, text: str) -> ReviewRef:
        """Parse user input; `id:X`/`number:N` are explicit, bare ASCII digits a number, other text an id."""
        if not text:
            raise ValueError("empty merge request reference")
        if text.startswith("id:"):
            if text == "id:":
                raise ValueError(f"empty merge request id in {text!r}")
            return cls(id=text.removeprefix("id:"))
        if text.startswith("number:"):
            digits = text.removeprefix("number:")
            if not _ASCII_DIGITS.fullmatch(digits):
                raise ValueError(f"not a merge request number: {text!r}")
            return cls._from_digits(digits, text)
        if _ASCII_DIGITS.fullmatch(text):
            return cls._from_digits(text, text)
        return cls(id=text)

    @classmethod
    def _from_digits(cls, digits: str, text: str) -> ReviewRef:
        try:
            number = int(digits)
        except ValueError:  # beyond the interpreter's int-conversion digit limit
            raise ValueError(f"merge request number too large: {digits[:20]}…") from None
        if number == 0:
            raise ValueError(f"merge request numbers start at 1, got {text!r}")
        return cls(number=number)

    @property
    def path_segment(self) -> str:
        """`number:N` or `id:X` with the raw id, as `reviewId` bodies expect."""
        return f"number:{self.number}" if self.number is not None else f"id:{self.id}"

    @property
    def url_segment(self) -> str:
        """`path_segment` with the id percent-encoded, so it stays one segment of a Space URL path."""
        if self.number is not None:
            return f"number:{self.number}"
        assert self.id is not None
        return f"id:{quote(self.id, safe='')}"

    @property
    def label(self) -> str:
        """The bare number, or `id:X`; both parse back to this ref."""
        return str(self.number) if self.number is not None else str(self)

    def __str__(self) -> str:
        return f"#{self.number}" if self.number is not None else f"id:{self.id}"
