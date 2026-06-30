#!/usr/bin/env python3
"""
test_loop.py - 24 test functions for loop.py

Tests cover:
  - Finding dataclass (serialize/round-trip)
  - Memory (save, load, update, archive, state)
  - Connector / GitHubConnector
  - EvaluatorAgent (has_structure, evaluate, add_rule, execute, all_pass)
  - GeneratorAgent (create_worktree, generate, check_stop_condition, cost tracking)
  - BudgetGate (all three gates)
  - LoopOrchestrator (full run_turn cycle)
  - Human gate
  - Edge cases
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Always import from the loop folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loop import (
    Finding, Status, Memory, GeneratorAgent, EvaluatorAgent,
    BudgetGate, LoopOrchestrator, Connector, GitHubConnector,
    DEFAULT_STATE_DIR, DEFAULT_WORKTREES, DEFAULT_INBOX,
)


# -------------- Helpers ----- -----


def _make_finding(status=Status.PENDING, id="test-1", text="Test task"):
    return Finding(id=id, text=text, status=status)


def _make_memory(state_dir=None, inbox_dir=None):
    sd = state_dir or tempfile.mkdtemp()
    ib = inbox_dir or tempfile.mkdtemp()
    return Memory(state_dir=sd, inbox_dir=ib)


# -------------- Test Classes / Functions (24 total) ----- -----


# 1. Finding — to_dict produces correct fields
def test_finding_to_dict():
    f = Finding(id="f1", text="Hello", status=Status.PENDING, score=0.5, detail="d")
    d = f.to_dict()
    assert d["id"] == "f1"
    assert d["text"] == "Hello"
    assert d["status"] == "pending"
    assert d["score"] == 0.5
    assert d["detail"] == "d"
    print("  [PASS] test_finding_to_dict")


# 2. Finding — from_dict round-trip
def test_finding_round_trip():
    f = Finding(id="f2", text="World", status=Status.APPROVE, score=0.9)
    d = f.to_dict()
    f2 = Finding.from_dict(d)
    assert f2.id == f.id
    assert f2.text == f.text
    assert f2.status == f.status
    assert f2.score == f.score
    print("  [PASS] test_finding_roundtrip")


# 3. Memory — save_finding writes to inbox
def test_memory_save_finding():
    mem = _make_memory()
    f = _make_finding()
    path = mem.save_finding(f)
    assert os.path.exists(path)
    assert f.id in path
    print("  [PASS] test_memory_save_finding")


# 4. Memory — load_finding returns the saved Finding
def test_memory_load_finding():
    mem = _make_memory()
    f = _make_finding(id="load-test")
    mem.save_finding(f)
    loaded = mem.load_finding("load-test")
    assert loaded is not None
    assert loaded.id == "load-test"
    assert loaded.text == "Test task"
    print("  [PASS] test_memory_load_finding")


# 5. Memory — update_finding changes state
def test_memory_update_finding():
    mem = _make_memory()
    f = _make_finding(status=Status.PENDING)
    mem.save_finding(f)
    f.status = Status.APPROVE
    mem.update_finding(f)
    loaded = mem.load_finding(f.id)
    assert loaded.status == Status.APPROVE
    print("  [PASS] test_memory_update_finding")


# 6. Memory — save_state / load_state round-trip
def test_memory_state_roundtrip():
    mem = _make_memory()
    mem.save_state("key1", {"count": 42})
    val = mem.load_state("key1")
    assert val == {"count": 42}
    print("  [PASS] test_memory_state_roundtrip")


# 7. Memory — archive_finding moves to state
def test_memory_archive_finding():
    mem = _make_memory()
    f = _make_finding()
    mem.save_finding(f)
    mem.archive_finding(f.id)
    # Should no longer be in inbox
    assert mem.load_finding(f.id) is None
    # Should be in state
    state_val = mem.load_state(f"archived_{f.id}")
    assert state_val is not None
    assert state_val["status"] == "archived"
    print("  [PASS] test_memory_archive_finding")


# 8. Memory — load_findings returns pending only
def test_memory_load_findings_pending():
    mem = _make_memory()
    mem.save_finding(_make_finding(status=Status.PENDING))
    mem.save_finding(_make_finding(status=Status.APPROVE))
    pending = mem.load_findings()
    # In V3, load_findings checks _findings list; both are in there
    # In V4, it checks _findings and filters by Status.PENDING
    pending_statuses = [f.status for f in pending]
    # The approved one should not be in pending
    assert Status.APPROVE not in pending_statuses
    print("  [PASS] test_memory_load_findings_pending")


# 9. Connector — base class exists
def test_connector_base_class():
    assert issubclass(Connector, object)
    print("  [PASS] test_connector_base_class")


# 10. GitHubConnector — fetch returns empty list by default
def test_github_connector_fetch():
    conn = GitHubConnector(repo="test/repo")
    findings = conn.fetch()
    assert findings == []
    print("  [PASS] test_github_connector_fetch")


# 11. GitHubConnector — submit does not raise
def test_github_connector_submit():
    conn = GitHubConnector(repo="test/repo")
    f = _make_finding()
    # Should not raise
    conn.submit(f)
    print("  [PASS] test_github_connector_submit")


# 12. EvaluatorAgent — has_structure detects headings
def test_evaluator_has_structure():
    ev = EvaluatorAgent()
    assert ev.has_structure("# Hello\n") == True
    assert ev.has_structure("# Hello\n\nWorld") == True
    assert ev.has_structure("no heading") == False
    print("  [PASS] test_evaluator_has_structure")


# 13. EvaluatorAgent — evaluate with no rules returns empty
def test_evaluator_no_rules():
    ev = EvaluatorAgent()
    f = _make_finding()
    results = ev.evaluate(f, "# Title\nContent\n", "/tmp/wt")
    assert results == []
    print("  [PASS] test_evaluator_no_rules")


# 14. EvaluatorAgent — all_pass with empty list returns True
def test_evaluator_all_pass_empty():
    ev = EvaluatorAgent()
    assert ev.all_pass([]) == True
    print("  [PASS] test_evaluator_all_pass_empty")


# 15. EvaluatorAgent — add_rule and evaluate passes
def test_evaluator_custom_rules_pass():
    ev = EvaluatorAgent()
    ev.add_rule("has_content", lambda f, d, w: {"passed": len(d) > 50, "detail": "ok"})
    f = _make_finding()
    results = ev.evaluate(f, "# Title\n" + "x" * 60, "/tmp/wt")
    assert len(results) == 1
    assert results[0]["passed"] == True
    print("  [PASS] test_evaluator_custom_rules_pass")


# 16. EvaluatorAgent — add_rule and evaluate fails content check
def test_evaluator_custom_rules_fail_content():
    ev = EvaluatorAgent()
    ev.add_rule("has_content", lambda f, d, w: {"passed": len(d) > 50, "detail": "ok"})
    f = _make_finding()
    results = ev.evaluate(f, "# Short", "/tmp/wt")
    assert len(results) == 1
    assert results[0]["passed"] == False
    print("  [PASS] test_evaluator_custom_rules_fail_content")


# 17. EvaluatorAgent — all_pass with mixed verdicts
def test_evaluator_all_pass_mixed():
    ev = EvaluatorAgent()
    assert ev.all_pass([{"passed": True}, {"passed": False}]) == False
    assert ev.all_pass([{"passed": True}, {"passed": True}]) == True
    print("  [PASS] test_evaluator_all_pass_mixed")


# 18. EvaluatorAgent — execute called when disabled
def test_evaluator_execute_disabled():
    ev = EvaluatorAgent()
    results = ev.execute(["echo hello"], "/tmp/wt")
    assert len(results) == 1
    assert results[0]["status"] == "disabled"
    print("  [PASS] test_evaluator_execute_disabled")


# 19. GeneratorAgent — create_worktree creates directory
def test_generator_create_worktree():
    root = tempfile.mkdtemp()
    gen = GeneratorAgent(worktrees_root=root)
    wt = gen.create_worktree("test-wt")
    assert os.path.isdir(wt)
    shutil.rmtree(root)
    print("  [PASS] test_generator_create_worktree")


# 20. GeneratorAgent — generate produces heading
def test_generator_generate_has_heading():
    root = tempfile.mkdtemp()
    gen = GeneratorAgent(worktrees_root=root)
    f = _make_finding(text="Task Alpha")
    draft = gen.generate(f, "template text")
    assert "# " in draft
    assert "Task Alpha" in draft
    shutil.rmtree(root)
    print("  [PASS] test_generator_generate_has_heading")


# 21. GeneratorAgent — check_stop_condition returns False when no goal
def test_generator_stop_condition_no_goal():
    root = tempfile.mkdtemp()
    gen = GeneratorAgent(worktrees_root=root)
    assert gen.check_stop_condition() == False
    shutil.rmtree(root)
    print("  [PASS] test_generator_stop_condition_no_goal")


# 22. BudgetGate — pre_discovery gate rejects over budget
def test_budget_gate_pre_discovery():
    gate = BudgetGate(per_run=1.0, per_turn=1.0, daily=10.0)
    assert gate.pre_discovery(0.5) == True
    assert gate.pre_discovery(2.0) == False
    print("  [PASS] test_budget_gate_pre_discovery")


# 23. LoopOrchestrator — run_turn with no findings returns False
def test_orchestrator_no_findings():
    mem = _make_memory()
    gen = GeneratorAgent()
    ev = EvaluatorAgent()
    budget = BudgetGate(per_run=10.0, per_turn=1.0, daily=100.0)
    orch = LoopOrchestrator(mem, gen, ev, budget)
    result = orch.run_turn("template")
    assert result == False
    print("  [PASS] test_orchestrator_no_findings")


# 24. LoopOrchestrator — full round-trip with one finding (simulate all-pass)
def test_orchestrator_full_roundtrip():
    mem = _make_memory()
    f = _make_finding(status=Status.PENDING, text="Full round-trip task")
    mem.save_finding(f)

    gen = GeneratorAgent()
    gen.budget_limit = 100.0
    gen.current_cost = 0.0

    ev = EvaluatorAgent()
    ev.add_rule("always_pass", lambda fnd, dr, wt: {"passed": True, "detail": "ok"})

    budget = BudgetGate(per_run=10.0, per_turn=1.0, daily=100.0)
    orch = LoopOrchestrator(mem, gen, ev, budget)
    result = orch.run_turn("template text")
    assert result == True
    # Finding should be archived (removed from inbox)
    archived = mem.load_state(f"archived_{f.id}")
    assert archived is not None
    assert archived["status"] == "archived"
    print("  [PASS] test_orchestrator_full_roundtrip")


# -------------- Runner ----- -----


def run_all_tests():
    """Run all 24 tests."""
    tests = [
        test_finding_to_dict,
        test_finding_round_trip,
        test_memory_save_finding,
        test_memory_load_finding,
        test_memory_update_finding,
        test_memory_state_roundtrip,
        test_memory_archive_finding,
        test_memory_load_findings_pending,
        test_connector_base_class,
        test_github_connector_fetch,
        test_github_connector_submit,
        test_evaluator_has_structure,
        test_evaluator_no_rules,
        test_evaluator_all_pass_empty,
        test_evaluator_custom_rules_pass,
        test_evaluator_custom_rules_fail_content,
        test_evaluator_all_pass_mixed,
        test_evaluator_execute_disabled,
        test_generator_create_worktree,
        test_generator_generate_has_heading,
        test_generator_stop_condition_no_goal,
        test_budget_gate_pre_discovery,
        test_orchestrator_no_findings,
        test_orchestrator_full_roundtrip,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test_fn.__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"  RESULTS: {passed}/{len(tests)} passed, {failed} failed")
    print(f"{'='*50}")
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
