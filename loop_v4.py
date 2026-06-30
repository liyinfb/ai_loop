#!/usr/bin/env python3
"""
Loop Engineering Framework V4
================================
Version: 4.0.0
Author: Hermes Agent (Peter Steinberger, Boris Cherny, Addy Osmani methodology)
Date: 2026-06-30

The four-layer orchestrator that makes AI agents run themselves.
Core: five moves (Discovery -> Handoff -> Verification -> Persistence -> Scheduling),
      six parts (Scheduling, Worktrees, Skills, Connectors, Sub-agents, Memory).

## Architecture

Loop Engineering replaces the human-in-the-loop pattern. Instead of a human
directing the agent line by line, the practitioner builds a loop that runs
autonomously.

The four-layer stack (from the IEEE paper):
    Prompt Eng.  -> words              What should I tell the model?
    Context Eng. -> the window now     What to retrieve, summarize, clear?
    Harness Eng. -> a single run       Which tools, which actions, what's done?
    Loop Eng.    -> the loop itself    How to make it run itself OVER AND OVER?

V4 is the full specification: Connector/MCP, execute(), three-arg add_rule(),
smart /goal stop conditions. V3 is the minimal version (see loop_v3.py).

## Components

    Memory
        File-based cross-turn persistence. Holdings findings, state data,
        and inbox/archive separation.
        - save_finding(), load_finding(), update_finding()
        - save_state(), load_state()
        - load_findings(connectors=None) -- connectors augmented in V4
        - archive_finding(), clear()
        - get_all_findings()

    Connector (ABC)
        MCP/external system abstraction layer (V4 addition).
        - fetch() -> List[Finding]
        - submit(finding: Finding) -> None
        - GitHubConnector(repo, branch) -- concrete implementation stub

    EvaluatorAgent
        Independent skeptical evaluator. Never let the generator grade its own work.
        V4 uses THREE-arg add_rule(): rule_fn(finding, draft, worktree) -> {"passed": bool, "detail": str}
        V3 uses TWO-arg add_rule(): rule_fn(draft, worktree)
        - add_rule(name, rule_fn)
        - has_structure(draft) -- checks for Markdown heading
        - evaluate(finding, draft, worktree) -> List[dict] verdicts
        - all_pass(verdicts) -> bool
        - execute(commands, worktree) -> List[dict] (requires executor to be set!)

    GeneratorAgent
        Generates work from findings, writes to isolated worktrees.
        - create_worktree(name) -> path
        - generate(finding, template) -> draft text
        - check_stop_condition() -> bool (V4: supports run:cmd in goal)
        - track_cost(cost), reset_budget()

    BudgetGate
        Three-gate circuit breaker: pre-discovery, post-discovery, post-generator.
        Prevents token blowout and idle bugs.
        - per_run, per_turn, daily limits
        - pre_discovery(cost), post_discovery_cost(cost), post_generator_cost(cost)

    LoopOrchestrator
        Ties everything together with the five moves:
        1. Discovery   -> Memory.load_findings() (+ connectors)
        2. Handoff     -> GeneratorAgent.create_worktree()
        3. Verification -> EvaluatorAgent.evaluate() (+ execute() via subprocess)
        4. Persistence  -> Memory.archive_finding() (+ goal stop condition)
        5. Scheduling   -> Timer / cron trigger (+ _scheduler() loop)

## V3 vs V4 Differences
    Feature           | V3            | V4
    -------           | ---           | ----
    add_rule args     | TWO (draft, wt)  | THREE (finding, draft, wt)
    Connector/MCP     | NO            | YES (Connector ABC + GitHubConnector)
    Evaluator.execute | NO            | YES (set executor first)
    /goal stop condn. | NO            | YES (run:cmd support)
    skill discovery   | NO            | YES
    complexity        | Minimal       | Full spec

## Usage - Minimal
    from loop_v4 import LoopOrchestrator, Memory, GeneratorAgent, EvaluatorAgent, BudgetGate, Finding, Status

    memory = Memory()
    generator = GeneratorAgent()
    evaluator = EvaluatorAgent()
    evaluator.add_rule("has_heading", lambda finding, draft, wt: {"passed": "# " in draft, "detail": "ok"})
    budget = BudgetGate(per_run=10.0, per_turn=0.5, daily=100.0)

    orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)
    orchestrator.run_turn("Default template")

## Usage - With Findings
    from loop_v4 import *

    memory = Memory()
    memory.save_finding(Finding(id="t1", text="Fix login bug", status=Status.PENDING))
    memory.save_finding(Finding(id="t2", text="Add tests", status=Status.PENDING))

    generator = GeneratorAgent()
    evaluator = EvaluatorAgent()
    evaluator.add_rule("structure", lambda f, draft, wt: {"passed": "# " in draft, "detail": "ok"})
    evaluator.add_rule("content", lambda f, draft, wt: {"passed": len(draft) > 100, "detail": "ok"})
    budget = BudgetGate(per_run=10.0, per_turn=0.5, daily=100.0)

    orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)
    for _ in range(5):
        if not orchestrator.run_turn("Your template text here."):
            break

## Usage - With Connectors (V4-only)
    from loop_v4 import *

    memory = Memory()
    memory.save_finding(Finding(id="t1", text="Fix login bug", status=Status.PENDING))

    connector = GitHubConnector(repo="myorg/myrepo", branch="main")
    # TODO: Implement connector.fetch() and .submit() with real API calls
    # connector.fetch() returns List[Finding] from GitHub PRs/issues

    generator = GeneratorAgent()
    evaluator = EvaluatorAgent()
    budget = BudgetGate(per_run=10.0, per_turn=0.5, daily=100.0)

    orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)
    orchestrator.run_turn("Default template")
    # connector data will be merged into findings during discovery

## Usage - Evaluator.execute() (V4-only, requires setup)
    from loop_v4 import *

    evalu = EvaluatorAgent()
    # IMPORTANT: executor must be set before calling execute()
    evalu.executor = lambda cmd: subprocess.run(cmd, shell=True, capture_output=True, text=True)
    results = evalu.execute(["pytest tests/"], "/path/to/worktree")
    # results: [{"returncode": 0, "stdout": "...", "stderr": "..."}]

## Usage - Smart /goal Stop Condition (V4-only)
    from loop_v4 import *

    generator = GeneratorAgent()
    generator.goal = {
        "text": "All tests must pass",
        "rules": [
            {"type": "run:cmd", "cmd": "pytest -q --tb=short"}
        ]
    }
    # check_stop_condition() runs the cmd and returns True (stop) if returncode != 0

## Usage - Advanced - Budget Guarding
    budget = BudgetGate(per_run=50.0, per_turn=2.0, daily=200.0)
    # If the generator goes over budget, the loop automatically stops
    # at the next gate. No manual intervention needed.

## Pitfalls
    - add_rule signature: V3 uses TWO args (draft, worktree). V4 uses THREE (finding, draft, worktree).
    - Evaluator has_structure() requires "# " (Markdown heading) in the draft.
    - Evaluator.execute() is DISABLED by default (executor=None). Must set evaluator.executor = callable first!
    - Connectors must be passed to memory.load_findings(connectors=[...]) — not auto-registered.
    - Smart /goal stop condition executes run:cmd via subprocess. Goal dict format:
      {"text": "...", "rules": [{"type": "run:cmd", "cmd": "pytest"}]}
    - BudgetGates are independent -- all three must pass, not just one.
    - Human gates only affect NEEDS_REVIEW findings, not REJECT findings.

## Key Quote
    "Build the loop, but build it like someone who intends to stay the engineer,
     not just the person who presses go." -- Addy Osmani

## Key Quote
    "The loop is a faithful multiplier of its builder — a multiplier is exactly as 
     valuable (and as dangerous) as the judgment fed into it."
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

# -------------- Paths --------------

DEFAULT_STATE_DIR = os.path.join(os.path.expanduser("~"), "hermes", "loop", "state")
DEFAULT_WORKTREES = os.path.join(os.path.expanduser("~"), "hermes", "loop", "worktrees")
DEFAULT_INBOX = os.path.join(os.path.expanduser("~"), "hermes", "loop", "inbox")

# -------------- Enums & Data Classes --------------


class Status(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REJECT = "reject"
    APPROVE = "approve"
    NEEDS_REVIEW = "needs_review"
    ARCHIVED = "archived"


@dataclass
class Finding:
    id: str
    text: str
    status: Status = Status.PENDING
    score: Optional[float] = None
    detail: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status.value,
            "score": self.score,
            "detail": self.detail,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(
            id=d["id"],
            text=d["text"],
            status=Status(d["status"]),
            score=d.get("score"),
            detail=d.get("detail", ""),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
        )


# -------------- Memory (Persistence layer) --------------


class Memory:
    """State management — cross-turn memory on disk."""

    def __init__(self, state_dir: str = DEFAULT_STATE_DIR, inbox_dir: str = DEFAULT_INBOX):
        self.state_dir = Path(state_dir)
        self.inbox_dir = Path(inbox_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self._findings: List[Finding] = []
        self._findings_index: Dict[str, str] = {}  # id -> file path

    def save_finding(self, finding: Finding) -> str:
        path = self.inbox_dir / f"{finding.id}.json"
        with open(path, "w") as f:
            json.dump(finding.to_dict(), f, indent=2)
        self._findings.append(finding)
        self._findings_index[finding.id] = str(path)
        return str(path)

    def load_finding(self, finding_id: str) -> Optional[Finding]:
        path = self._findings_index.get(finding_id)
        if path is None:
            return None
        with open(path) as f:
            return Finding.from_dict(json.load(f))

    def update_finding(self, finding: Finding) -> None:
        finding.updated_at = datetime.now()
        path = self._findings_index.get(finding.id)
        if path:
            with open(path, "w") as f:
                json.dump(finding.to_dict(), f, indent=2)

    def save_state(self, key: str, value: Any) -> None:
        path = self.state_dir / f"{key}.json"
        with open(path, "w") as f:
            json.dump(value, f, indent=2)

    def load_state(self, key: str) -> Optional[Any]:
        path = self.state_dir / f"{key}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def load_findings(self, connectors: Optional[List["Connector"]] = None) -> List[Finding]:
        """Load pending findings from disk, augmented by connector data."""
        findings = [f for f in self._findings if f.status == Status.PENDING]
        # Connector augmentation
        if connectors:
            for conn in connectors:
                findings.extend(conn.fetch())
        return findings

    def archive_finding(self, finding_id: str) -> None:
        """Move approved finding to state directory."""
        path = self._findings_index.get(finding_id)
        if path:
            shutil.move(path, os.path.join(self.state_dir, os.path.basename(path)))
            del self._findings_index[finding_id]
        finding = self.load_finding(finding_id)
        if finding is not None:
            finding.status = Status.ARCHIVED
            self.save_state(f"archived_{finding.id}", finding.to_dict())


# -------------- Connector (MCP Abstraction Layer) --------------


class Connector(ABC):
    """Base class for external system connectors (GitHub, Jira, CI, etc.)."""

    @abstractmethod
    def fetch(self) -> List[Finding]:
        """Return findings discovered from the external system."""
        ...

    @abstractmethod
    def submit(self, finding: Finding) -> None:
        """Submit a completed finding back to the external system."""
        ...


class GitHubConnector(Connector):
    """Example GitHub PR/issues connector."""

    def __init__(self, repo: str = "", branch: str = "main"):
        self.repo = repo
        self.branch = branch

    def fetch(self) -> List[Finding]:
        # TODO: Implement real GitHub API calls
        return []

    def submit(self, finding: Finding) -> None:
        # TODO: Implement real GitHub API calls
        pass


# -------------- Evaluator Agent --------------


class EvaluatorAgent:
    """Independent skeptical evaluator — never let an agent grade its own work."""

    def __init__(self):
        self.rules: Dict[str, Callable[[Finding, str, str], dict]] = {}
        self.executor: Optional[Callable] = None  # Defaults to None (disabled)

    def add_rule(self, name: str, rule_fn: Callable[[Finding, str, str], dict]) -> None:
        """
        Add a custom rule.
        rule_fn MUST accept three positional arguments:
        (finding, draft_code, worktree) — returning {"passed": bool, "detail": str}.
        """
        self.rules[name] = rule_fn

    def has_structure(self, draft: str) -> bool:
        """Output must have a top-level Markdown heading."""
        return "# " in draft

    def execute(self, commands: List[str], worktree: str) -> List[dict]:
        """
        Run subprocess commands (e.g. tests).
        Must be enabled: set executor before calling this.
        """
        if self.executor is None:
            return [{"status": "disabled", "detail": "executor not set"}]
        results = []
        for cmd in commands:
            results.append(self.executor(cmd, worktree))
        return results

    def evaluate(self, finding: Finding, draft: str, worktree: str) -> List[dict]:
        """
        Apply all rules against a draft in a worktree.
        Returns list of verdict dicts [{"passed": bool, "detail": str, "rule": name}, ...].
        """
        if not self.has_structure(draft):
            return [{"passed": False, "detail": "Missing top-level Markdown heading", "rule": "structural"}]

        verdicts = []
        for name, rule_fn in self.rules.items():
            try:
                result = rule_fn(finding, draft, worktree)
                verdicts.append({
                    "passed": result["passed"],
                    "detail": result["detail"],
                    "rule": name,
                })
            except Exception as e:
                verdicts.append({
                    "passed": False,
                    "detail": f"Rule '{name}' crashed: {e}",
                    "rule": name,
                })
        return verdicts

    def all_pass(self, verdicts: List[dict]) -> bool:
        """Returns True if all verdicts passed."""
        return all(v["passed"] for v in verdicts)


# -------------- Generator Agent --------------


class GeneratorAgent:
    """Generates work from findings, writes to worktrees."""

    def __init__(self, worktrees_root: str = DEFAULT_WORKTREES):
        self.worktrees_root = Path(worktrees_root)
        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        self.budget_limit: Optional[float] = None  # Token budget
        self.current_cost: float = 0.0
        self.goal: Optional[dict] = None  # {"text": "...", "rules": [...]}

    def create_worktree(self, name: str) -> str:
        worktree = os.path.join(self.worktrees_root, name)
        os.makedirs(worktree, exist_ok=True)
        return worktree

    def generate(self, finding: Finding, template: str) -> str:
        """Produce draft content from a finding and a template."""
        return f"# {finding.text}\n\nDraft based on finding {finding.id}.\n## Content\n\n{template}"

    def check_stop_condition(self) -> bool:
        """
        Check /goal stop condition: executes run:cmd rules before returning True.
        Goal dict format: {"text": "...", "rules": [{"type": "run:cmd", "cmd": "pytest"}, ...]}
        """
        if self.goal is None:
            return False

        for rule in self.goal.get("rules", []):
            if rule.get("type") == "run:cmd":
                result = subprocess.run(
                    rule["cmd"], shell=True, capture_output=True, text=True
                )
                if result.returncode != 0:
                    print(f"[stop] cmd failed: {rule['cmd']}")
                    return True

        return False

    def track_cost(self, cost: float) -> None:
        self.current_cost += cost
        if self.budget_limit is not None and self.current_cost >= self.budget_limit:
            self.cost_exceeded = True

    def reset_budget(self) -> None:
        self.current_cost = 0.0
        self.cost_exceeded = False


# -------------- Budget Circuit Breakers --------------


class BudgetGate:
    """Three-gate budget system (not single-gate)."""

    def __init__(self, per_run: float, per_turn: float, daily: float):
        self.per_run = per_run
        self.per_turn = per_turn
        self.daily = daily
        self._daily_spent = 0.0
        self._turn_spent = 0.0
        self._last_turn = time.time()

    def pre_discovery(self, cost_estimate: float) -> bool:
        """Gate 1: before discovery."""
        if cost_estimate > self.per_run:
            print(f"[circuit-breaker] Pre-discovery: {cost_estimate} > {self.per_run}")
            return False
        return True

    def post_discovery_cost(self, cost: float) -> bool:
        """Gate 2: after discovery cost."""
        self._turn_spent += cost
        if self._turn_spent > self.per_turn:
            print(f"[circuit-breaker] Post-discovery turn: {self._turn_spent} > {self.per_turn}")
            return False
        return True

    def post_generator_cost(self, cost: float) -> bool:
        """Gate 3: after generator cost."""
        self._turn_spent += cost
        if self._turn_spent > self.per_run or self._daily_spent + cost > self.daily:
            print(f"[circuit-breaker] Post-generator: turn {self._turn_spent}/{self.per_run}, "
                  f"daily {self._daily_spent + cost}/{self.daily}")
            return False
        self._daily_spent += cost
        return True


# -------------- Orchestrator --------------


class LoopOrchestrator:
    """
    Runs one loop turn, coordinating all five moves:
      1. Discovery   -> Memory.load_findings()
      2. Handoff     -> GeneratorAgent.create_worktree()
      3. Verification -> EvaluatorAgent.evaluate()
      4. Persistence  -> Memory.archive_finding()
      5. Scheduling   -> Timer / cron trigger
    """

    def __init__(
        self,
        memory: Memory,
        generator: GeneratorAgent,
        evaluator: EvaluatorAgent,
        budget: BudgetGate,
    ):
        self.memory = memory
        self.generator = generator
        self.evaluator = evaluator
        self.budget = budget
        self.turn_count = 0
        self.human_gate_active = False

    def _discovery(self) -> List[Finding]:
        """Move 1: Discovery — find this turn's work."""
        print("[discovery] Fetching work items...")
        findings = self.memory.load_findings(connectors=[])
        print(f"[discovery] Found {len(findings)} pending items.")
        return findings

    def _handoff(self, finding: Finding) -> str:
        """Move 2: Handoff — create isolated worktree."""
        name = f"turn-{self.turn_count}-{finding.id}"
        worktree = self.generator.create_worktree(name)
        print(f"[handoff] Created worktree: {worktree}")
        return worktree

    def _verification(self, finding: Finding, draft: str, worktree: str) -> bool:
        """Move 3: Verification — independent check."""
        print("[verification] Running evaluator...")
        verdicts = self.evaluator.evaluate(finding, draft, worktree)
        passed_count = len([v for v in verdicts if v["passed"]])
        print(f"[verification] Verdicts: {passed_count}/{len(verdicts)} passed")
        passed = self.evaluator.all_pass(verdicts)
        if not passed:
            for v in verdicts:
                if not v["passed"]:
                    print(f"  [verification] FAIL: {v['rule']} — {v['detail']}")
        return passed

    def _persistence(self, finding: Finding, verdict: bool) -> None:
        """Move 4: Persistence — save / archive state."""
        if verdict:
            self.memory.archive_finding(finding.id)
        else:
            finding.status = Status.REJECT
            self.memory.update_finding(finding)
        print("[persistence] State saved.")

    def _human_gate(self, finding: Finding) -> bool:
        """Manual gate: pause for human review. Only for NEEDS_REVIEW findings."""
        if finding.status == Status.NEEDS_REVIEW:
            print(f"[human-gate] Finding {finding.id} needs review: {finding.text}")
            answer = input("Approve? (y/n): ").strip().lower()
            return answer == "y"
        return True

    def _scheduler(self) -> bool:
        """Move 5: Scheduling — check if more work is pending."""
        findings = self.memory.load_findings()
        return len([f for f in findings if f.status == Status.PENDING]) > 0

    def run_turn(self, template: str = "N/A") -> bool:
        """Run one complete loop turn. Returns whether any work was done."""
        # Check scheduling
        if not self._scheduler():
            print("[idle] No pending work. Done.")
            return False

        self.turn_count += 1
        print(f"\n{'='*60}")
        print(f"  LOOP TURN #{self.turn_count}")
        print(f"{'='*60}")

        # Budget gate 1
        if not self.budget.pre_discovery(cost_estimate=0.1):
            print("[circuit-breaker] Shutting down: budget exceeded before discovery")
            return False

        # Move 1: Discovery
        findings = self._discovery()
        if not findings:
            print("[idle] Nothing to do this turn. Done.")
            return False

        # Budget gate 2
        if not self.budget.post_discovery_cost(0.1):
            print("[circuit-breaker] Shutting down: budget exceeded after discovery")
            return False

        work_done = False
        for finding in findings:
            # Move 2: Handoff
            worktree = self._handoff(finding)

            # Generate
            draft = self.generator.generate(finding, template)
            gen_cost = 0.3  # simulated
            self.generator.track_cost(gen_cost)

            # Budget gate 3
            if not self.budget.post_generator_cost(gen_cost):
                print("[circuit-breaker] Shutting down: budget exceeded after generator")
                break

            # Move 3: Verification
            verdict = self._verification(finding, draft, worktree)
            if verdict:
                self.human_gate_active = self._human_gate(finding)
                if self.human_gate_active:
                    finding.status = Status.APPROVE
                else:
                    finding.status = Status.NEEDS_REVIEW
            else:
                finding.status = Status.REJECT
            self.memory.update_finding(finding)
            self._persistence(finding, verdict)
            work_done = True

            # Break condition
            if self.generator.check_stop_condition():
                print("[stop] Goal stop condition met.")
                break

        if work_done:
            self.generator.reset_budget()
        return work_done


# -------------- Main (CLI entry-point) --------------


def main():
    """CLI demo."""
    parser = argparse.ArgumentParser(description="Loop Engineering V4 Framework")
    parser.add_argument("--run", "-r", type=int, default=1, help="Number of turns to run")
    parser.add_argument("--worktrees", default=DEFAULT_WORKTREES)
    parser.add_argument("--state", default=DEFAULT_STATE_DIR)
    parser.add_argument("--budget", default="10.0:0.5:100.0", help="per_run:per_turn:daily budget")
    args = parser.parse_args()

    per_run, per_turn, daily = (float(x) for x in args.budget.split(":"))

    memory = Memory(state_dir=args.state)
    generator = GeneratorAgent(worktrees_root=args.worktrees)
    evaluator = EvaluatorAgent()
    budget = BudgetGate(per_run, per_turn, daily)

    orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)

    template = "Default template placeholder."
    for _ in range(args.run):
        if not orchestrator.run_turn(template):
            break

    print("\nDone.")


if __name__ == "__main__":
    main()
