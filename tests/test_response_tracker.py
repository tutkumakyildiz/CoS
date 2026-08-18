"""Tests for ResponseTracker's pure state logic (no Strands Agent needed —
just feeds it fake AfterToolCallEvent-shaped tool_use dicts directly)."""

from __future__ import annotations

from types import SimpleNamespace

from cos.response_tracker import ResponseTracker


def _fake_event(tool_name: str) -> SimpleNamespace:
    return SimpleNamespace(tool_use={"name": tool_name})


def test_no_tools_used_is_not_did_work_without_replying():
    tracker = ResponseTracker()
    assert tracker.did_work_without_replying is False


def test_read_tool_without_reply_tool_is_did_work_without_replying():
    tracker = ResponseTracker()
    tracker._on_after_tool_call(_fake_event("get_open_tasks"))
    assert tracker.any_tool_used is True
    assert tracker.responded is False
    assert tracker.did_work_without_replying is True


def test_send_message_counts_as_responded():
    tracker = ResponseTracker()
    tracker._on_after_tool_call(_fake_event("get_open_tasks"))
    tracker._on_after_tool_call(_fake_event("send_message"))
    assert tracker.responded is True
    assert tracker.did_work_without_replying is False


def test_ask_choice_counts_as_responded():
    tracker = ResponseTracker()
    tracker._on_after_tool_call(_fake_event("ask_choice"))
    assert tracker.responded is True
    assert tracker.did_work_without_replying is False


def test_reset_clears_state():
    tracker = ResponseTracker()
    tracker._on_after_tool_call(_fake_event("send_message"))
    tracker.reset()
    assert tracker.any_tool_used is False
    assert tracker.responded is False
    assert tracker.did_work_without_replying is False
