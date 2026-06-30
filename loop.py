#!/usr/bin/env python3
"""
Loop Engineering Framework — Initial Version (V1)
================================

The very first implementation of the Loop Engineering framework.
Basic loop structure with five moves and six parts conceptually present
but not fully abstracted. This was the starting point before V3 and V4.

Core loop structure:
  1. Discover -> Find this turn's work
  2. Handoff  -> Create isolated worktree
  3. Verify   -> Independent check
  4. Persist  -> Save state
  5. Schedule -> Run on a timer

Parts present:
  - Worktrees (isolated dirs for parallel agents)
  - Memory (state files on disk)
  - Basic evaluator (rule-based checking)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any


# -------------- Paths --------------

STATE_DIR = os.path.expanduser("~/hermes/loop/state")
WORKTREES = os.path.expanduser("~/hermes/loop/worktrees")
INBOX = os.path.expanduser("~/hermes/loop/inbox")


# -------------- Enums --------------


class Status(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPROVE = "approve"
    REJECT = "reject"
    NEEDS_REVIEW = "needs_review"


# -------------- Data Classes --------------


@dataclass
class Finding:
    """A task/work item discovered by the loop."""
    id: str
    text: str
    status: str = "pending"
    score: Optional[float] = None
    detail: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class Worktree:
    """An isolated working directory for a single task."""
    name: str
    path: str
    task_id: str
    created_at: float = field(default_factory=time.time)


# -------------- Core Loop Classes --------------


class Memory:
    """Simple file-based state persistence."""

    def __init__(self, state_dir: str = STATE_DIR, inbox_dir: str = INBOX):
        self.state_dir = Path(state_dir)
        self.inbox_dir = Path(inbox_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._findings = []

    def save_finding(self, f: Finding):
        """Save a finding to inbox."""
        fname = f"{f.id}.json"
        data = {
            "id": f.id,
            "text": f.text,
            "status": f.status,
            "score": f.score,
            "detail": f.detail,
            "time": f.created_at,
        }
        with open(self.inbox_dir / fname, "w") as fp:
            json.dump(data, fp)
        self._findings.append(f)

    def load_pending(self):
        """Load all pending findings from inbox."""
        result = []
        for path in self.inbox_dir.glob("*.json"):
            with open(path) as fp:
                data = json.load(fp)
            if data["status"] == "pending":
                result.append(Finding(**data))
        return result

    def archive(self, finding_id: str):
        """Move a finding from inbox to state (archive)."""
        src = self.inbox_dir / f"{finding_id}.json"
        dst = self.state_dir / f"{finding_id}.json"
        if src.exists():
            src.rename(dst)


class Evaluator:
    """Simple rule-based verifier."""

    def __init__(self):
        self.rules = []

    def add_rule(self, name, check_fn):
        """Add a check rule: name -> function(draft_content) -> bool."""
        self.rules.append((name, check_fn))

    def evaluate(self, draft: str) -> dict:
        """Run all rules against draft content. Return {rule_name: passed}."""
        results = {}
        for name, check_fn in self.rules:
            try:
                results[name] = check_fn(draft)
            except Exception as e:
                results[name] = False
        return results

    def passed_all(self, results: dict) -> bool:
        return all(results.values())


class Logger:
    """Simple logging utility."""

    def __init__(self):
        self._logs = []

    def info(self, msg: str):
        self._logs.append(f"[INFO]  {msg}")
        print(f"[INFO]  {msg}")

    def warn(self, msg: str):
        self._logs.append(f"[WARN]  {msg}")
        print(f"[WARN]  {msg}")

    def error(self, msg: str):
        self._logs.append(f"[ERROR] {msg}")
        print(f"[ERROR] {msg}")

    def get_logs(self):
        return self._logs


class LoopEngine:
    """
    The core loop engine — runs the five moves repeatedly.

    Five moves per turn:
      1. DISCOVER   — Load pending findings from Memory
      2. HANDOFF    — Create isolated worktree
      3. GENERATE   — Create draft content (placeholder for LLM call)
      4. VERIFY     — Run Evaluator rules against draft
      5. PERSIST    — Archive approved findings or reject failed ones

    The loop continues until there is no more pending work or budget runs out.
    """

    def __init__(self, budget_per_run: float = 100.0):
        self.memory = Memory()
        self.evaluator = Evaluator()
        self.logger = Logger()
        self.budget_per_run = budget_per_run
        self.current_budget = budget_per_run
        self.turn_count = 0
        self.worktrees = []

    def setup_rules(self):
        """Add default validation rules."""
        def check_heading(draft):
            """Draft must have a Markdown heading."""
            return "# " in draft or "##" in draft

        def check_content_length(draft):
            """Draft must have meaningful content (> 100 chars)."""
            return len(draft) > 100

        self.evaluator.add_rule("has_heading", check_heading)
        self.evaluator.add_rule("has_content", check_content_length)

    def _discover(self):
        """Move 1: Find pending work."""
        findings = self.memory.load_pending()
        self.logger.info(f"DISCOVER: Found {len(findings)} pending findings.")
        return findings

    def _handoff(self, finding):
        """Move 2: Create isolated worktree for this task."""
        name = f"worktree_{finding.id.replace(' ', '_')}"
        path = os.path.join(WORKTREES, name)
        os.makedirs(path, exist_ok=True)
        wt = Worktree(name=name, path=path, task_id=finding.id)
        self.worktrees.append(wt)
        self.logger.info(f"HANDOFF: Created worktree '{name}' for '{finding.id}'.")
        return wt

    def _generate(self, finding, template="Default template"):
        """Move 2.5: Generate draft (placeholder for LLM call)."""
        draft = f"# {finding.text}\n\nDraft based on finding {finding.id}.\n## Content\n\n{template}"
        self.logger.info(f"GENERATE: Created draft for '{finding.id}'.")
        return draft

    def _verify(self, draft: str):
        """Move 3: Run evaluation rules."""
        results = self.evaluator.evaluate(draft)
        passed = self.evaluator.passed_all(results)
        self.logger.info(f"VERIFY: Results = {results}  ->  {'PASS' if passed else 'FAIL'}")
        return results, passed

    def _persist(self, finding, passed: bool):
        """Move 4: Archive or reject."""
        if passed:
            finding.status = "approve"
            self.memory.archive(finding.id)
            self.logger.info(f"PERSIST: Archived finding '{finding.id}'.")
        else:
            finding.status = "reject"
            self.logger.info(f"PERSIST: Rejected finding '{finding.id}'.")

    def run(self, num_turns: int = 5, template: str = "Default template"):
        """
        Run the loop for up to num_turns cycles.
        Returns list of (finding, verdict) tuples.
        """
        self.setup_rules()
        self.current_budget = self.budget_per_run
        all_results = []

        for turn in range(num_turns):
            self.turn_count += 1
            self.logger.info(f"\n=== TURN {self.turn_count} ===")

            if self.current_budget <= 0:
                self.logger.warn("BUDGET: Budget exhausted. Stopping.")
                break

            # Move 1: Discover
            findings = self._discover()
            if not findings:
                self.logger.info("SKIP: No pending work. Loop complete.")
                break

            # Process each finding
            found_work = False
            for finding in findings:
                # Move 2: Handoff
                worktree = self._handoff(finding)

                # Move 2.5: Generate
                draft = self._generate(finding, template)

                # Move 3: Verify
                _results, passed = self._verify(draft)

                # Move 4: Persist
                self._persist(finding, passed)

                all_results.append((finding, "PASS" if passed else "FAIL"))
                self.current_budget -= 0.5  # Simulated cost per finding
                found_work = True

            if not found_work:
                break

        return all_results


def main():
    """CLI demo."""
    engine = LoopEngine(budget_per_run=100.0)

    # Add some sample findings
    engine.memory.save_finding(Finding(id="task1", text="Write test for user login"))
    engine.memory.save_finding(Finding(id="task2", text="Fix CSS overflow"))
    engine.memory.save_finding(Finding(id="task3", text="Add logging to API"))

    print("="*60)
    print("  Loop Engineering Framework — Initial Version (V1)")
    print("="*60)

    results = engine.run(num_turns=3)

    print("\n" + "="*60)
    print("  RESULTS")
    print("="*60)
    for finding, verdict in results:
        print(f"  {finding.id:15s} -> {verdict}")

    print(f"\n  {engine.turn_count} turns completed.")
    print("="*60)


if __name__ == "__main__":
    main()
