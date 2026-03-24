"""Tests for shared formatting utilities."""

from space.formatting import human_size


class TestHumanSize:

    def test_bytes(self):
        assert human_size(500) == "500 B"

    def test_kilobytes(self):
        assert human_size(4096) == "4.0 KB"

    def test_megabytes(self):
        assert human_size(1048576) == "1.0 MB"

    def test_none(self):
        assert human_size(None) == ""

    def test_zero(self):
        assert human_size(0) == "0 B"
