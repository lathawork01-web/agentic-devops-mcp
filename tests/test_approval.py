"""
Tests for approval.py — the safety-critical piece of this project.
These run without any live infrastructure, so they're safe for CI.
"""

import sys
import os
import time
import json
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp_server"))

import approval

# Route the audit log to a temp file for the duration of these tests, so
# test runs don't pollute (or depend on) the real audit_log.jsonl.
_tmp_audit_file = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
approval.AUDIT_LOG_PATH = _tmp_audit_file.name


def test_propose_does_not_execute_immediately():
    executed = {"called": False}

    def fake_action():
        executed["called"] = True
        return "done"

    result = approval.propose_action("test action", fake_action)

    assert "confirmation_token" in result
    assert executed["called"] is False, "Action must NOT run until confirm_action is called"


def test_confirm_executes_the_action():
    executed = {"called": False}

    def fake_action():
        executed["called"] = True
        return "done"

    proposal = approval.propose_action("test action", fake_action)
    result = approval.confirm_action(proposal["confirmation_token"])

    assert executed["called"] is True
    assert "Executed" in result


def test_token_is_single_use():
    proposal = approval.propose_action("test action", lambda: "done")
    token = proposal["confirmation_token"]

    first = approval.confirm_action(token)
    second = approval.confirm_action(token)

    assert "Executed" in first
    assert "already been executed" in second


def test_invalid_token_rejected():
    result = approval.confirm_action("not-a-real-token")
    assert "Invalid" in result


def test_expired_token_rejected():
    proposal = approval.propose_action("test action", lambda: "done")
    token = proposal["confirmation_token"]

    # Simulate expiry by manually rewinding the creation timestamp
    approval._pending_actions[token]["created_at"] = time.time() - 1000

    result = approval.confirm_action(token)
    assert "expired" in result


def test_decline_action_discards_without_executing():
    executed = {"called": False}

    def fake_action():
        executed["called"] = True
        return "done"

    proposal = approval.propose_action("test action", fake_action)
    token = proposal["confirmation_token"]

    result = approval.decline_action(token, reason="testing decline")
    assert "declined" in result.lower()
    assert executed["called"] is False

    # A declined token should no longer be usable at all
    confirm_result = approval.confirm_action(token)
    assert "Invalid" in confirm_result


def test_audit_log_records_full_lifecycle():
    proposal = approval.propose_action("audited action", lambda: "ok", action_type="test_type")
    token = proposal["confirmation_token"]
    approval.confirm_action(token)

    entries = approval.read_audit_log(limit=10)
    events = [e["event"] for e in entries]

    assert "proposed" in events
    assert "confirmed_and_executed" in events

    proposed_entry = next(e for e in entries if e["event"] == "proposed" and e["token"] == token)
    assert proposed_entry["action_type"] == "test_type"

    executed_entry = next(e for e in entries if e["event"] == "confirmed_and_executed" and e["token"] == token)
    assert executed_entry["result"] == "ok"


def test_audit_log_records_rejections():
    result = approval.confirm_action("definitely-not-a-real-token")
    assert "Invalid" in result

    entries = approval.read_audit_log(limit=5)
    assert any(e["event"] == "confirm_rejected" and e["reason"] == "invalid_or_unknown_token" for e in entries)


if __name__ == "__main__":
    test_propose_does_not_execute_immediately()
    test_confirm_executes_the_action()
    test_token_is_single_use()
    test_invalid_token_rejected()
    test_expired_token_rejected()
    test_decline_action_discards_without_executing()
    test_audit_log_records_full_lifecycle()
    test_audit_log_records_rejections()
    print("All approval tests passed.")

    os.unlink(_tmp_audit_file.name)
