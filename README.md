# Loop Engineering Framework

The four-layer orchestrator that makes AI agents run themselves — no human-in-the-loop required.

**Based on the methodology of Peter Steinberger, Boris Cherny & Addy Osmani.**  
*IEEE paper: "Loop Engineering for AI Agent Workflow Automation"*

## TL;DR in three moves

```python
from loop import LoopOrchestrator, Memory, GeneratorAgent, EvaluatorAgent, BudgetGate, Finding, Status

memory = Memory()
generator = GeneratorAgent()
evaluator = EvaluatorAgent()
evaluator.add_rule("has_heading", lambda f, d, w: {"passed": "# " in d, "detail": "ok"})
budget = BudgetGate(per_run=10.0, per_turn=0.5, daily=100.0)

orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)
orchestrator.run_turn("Your prompt template here.")
```

One call, five moves. The loop runs until there is no work left.

## The four-layer stack

| Layer | Problem it solves |
|---|---|
| **Prompt Eng.** | What should I tell the model? |
| **Context Eng.** | What to retrieve / summarize / clear in the window? |
| **Harness Eng.** | Which tools, which actions, what's done? |
| **Loop Eng.** | How do I make this run over and over by itself? |

## Five moves, six parts

**Five moves** (the heart of every loop):

1. **Discovery** — `Memory.load_findings()` (load pending tasks)
2. **Handoff** — `GeneratorAgent.create_worktree()` (isolate work in scratch space)
3. **Verification** — `EvaluatorAgent.evaluate()` (independent skeptic, not the generator)
4. **Persistence** — `Memory.archive_finding()` (commit approved work)
5. **Scheduling** — auto-check for more pending items

**Six parts** that make it useful:

- **[Scheduling](#scheduling)** — turn counter + cron/loop trigger
- **[Worktrees](#worktrees)** — isolated `/tmp`-like scratch for each finding
- **[Skills](#skills)** — reusable prompt templates you inject at handoff
- **[Connectors](#connectors)** — plug in GitHub, Jira, CI, MCP
- **[Sub-agents](#sub-agents)** — one agent generates, another reviews
- **[Memory](#memory)** — cross-turn storage with inbox → state → archive

## Quickstart

```bash
cd ~/hermes/loop
python -m loop --run 3                # Run 3 turns from disk findings
python -m loop --run 3 --budget 50:2:200  # Set budget gates (per_run:per_turn:daily)
python -m loop --run 3 --worktrees /tmp/loop-wtrees --state /tmp/loop-state
```

### Natural language input

Give `TaskPlannerAgent` a plain-English goal — it auto-generates findings + template:

```python
from loop import (
    LoopOrchestrator, Memory, GeneratorAgent,
    EvaluatorAgent, BudgetGate, TaskPlannerAgent,
)

planner = TaskPlannerAgent()

# Pass a natural-language goal
findings, template = planner.parse(
    goal_text="Add a REST API for user management with Flask.\n"
              "Need login, registration, and database models."
)
# → findings auto-generated (e.g. [task-a-1: Add login endpoint, ...])
# → template filled with domain-specific requirements for "api"

memory = Memory()
for f in findings:
    memory.save_finding(f)

generator = GeneratorAgent()
evaluator = EvaluatorAgent()
evaluator.add_rule("has_heading", lambda f, d, w: {"passed": "# " in d, "detail": "ok"})
budget = BudgetGate(per_run=10.0, per_turn=0.5, daily=100.0)

orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)

for _ in range(5):
    if not orchestrator.run_turn(template):
        break
```

## Architecture

### `Finding` — the unit of work

```python
from loop import Finding, Status

f = Finding(id="t1", text="Fix login bug", status=Status.PENDING)
f = Finding.from_dict(json_dict)  # deserialize
d = f.to_dict()                   # serialize
```

**Statuses**: `PENDING` → `IN_PROGRESS` → (`REJECT` | `APPROVE` | `NEEDS_REVIEW` | `ARCHIVED`)

### `Memory` — persistence layer

```python
from loop import Memory

memory = Memory()
memory.save_finding(Finding(id="t1", text="Fix login bug"))

# Load pending findings (not archived/rejected)
pending = memory.load_findings()  # or load_findings(connectors=[...])

memory.archive_finding("t1")  # move approved → state archive
```

**Directories** (customizable):

| Path | Purpose |
|---|---|
| `~/hermes/loop/inbox/` | Pending findings (JSON files) |
| `~/hermes/loop/state/` | Archived results and state |
| `~/hermes/loop/worktrees/` | Isolated work directories |

### `Connector` — plug in external systems

```python
from loop import Connector, GitHubConnector, Finding, Status

class SlackConnector(Connector):
    def fetch(self):
        # Pull pending tasks from Slack/Slack API
        return [Finding(id="s1", text="New message")]

    def submit(self, finding: Finding):
        # Reply to the Slack thread with the result
        pass
```

**Built-in stub**: `GitHubConnector(repo="org/repo", branch="main")`  
Call `memory.load_findings(connectors=[connector])` to merge external findings into the loop.

### `EvaluatorAgent` — independent reviewer

> **Rule of thumb:** Never let the generator grade its own work.

```python
from loop import EvaluatorAgent, Finding

evaluator = EvaluatorAgent()
evaluator.add_rule("has_heading", lambda f, d, w: {"passed": "# " in d, "detail": "ok"})
evaluator.add_rule("content_length", lambda f, d, w: {"passed": len(d) > 100, "detail": f"len={len(d)}"})

# Evaluate a draft in a worktree
verdicts = evaluator.evaluate(finding, draft_text, "/path/to/worktree")
# → [{"passed": True, "detail": "ok", "rule": "has_heading"}, ...]

evaluator.all_pass(verdicts)  # True/False

# Has_structure check is automatic: rejects drafts without Markdown headings
```

**Three-arg signature**: `add_rule("name", lambda finding, draft, worktree: {...})`

### `EvaluatorAgent.execute()` — subprocess execution

```python
evaluator.executor = lambda cmd: subprocess.run(cmd, shell=True, capture_output=True, text=True)
results = evaluator.execute(["pytest tests/"], "/path/to/worktree")
# → [{"returncode": 0, "stdout": "...", "stderr": "..."}]
```

⚠️ **Disabled by default** (`executor=None`). Must set a callable executor first.

### `GeneratorAgent` — the worker

```python
from loop import GeneratorAgent

generator = GeneratorAgent()
worktree = generator.create_worktree("fix-login")  # → ~/hermes/loop/worktrees/fix-login
draft = generator.generate(finding, "Your template text.")  # produces Markdown
```

**Goal stop condition**:

```python
generator.goal = {
    "text": "All tests must pass",
    "rules": [
        {"type": "run:cmd", "cmd": "pytest -q --tb=short"},
    ]
}
generator.check_stop_condition()  # runs the cmd, returns True to stop the loop
```

**Budget tracking**:

```python
generator.track_cost(0.5)  # add to current run cost
generator.budget_limit = 50.0  # optional hard cap
generator.reset_budget()   # reset per-turn counters
```

### `BudgetGate` — three-gate circuit breaker

Three independent gates — **all** must pass:

| Gate | Trigger | Purpose |
|---|---|---|
| **Pre-discovery** | Before fetching work | Stop expensive jobs |
| **Post-discovery** | After loading findings | Prevent idle loops (→ 0 findings) |
| **Post-generator** | After generation | Token / cost budget |

```python
from loop import BudgetGate

budget = BudgetGate(
    per_run=50.0,   # Max tokens/costs per full run
    per_turn=2.0,   # Max tokens/costs per single discovery fetch
    daily=200.0,    # Total daily budget
)
```

### `LoopOrchestrator` — the core loop

Ties everything together and runs all five moves for each turn.

```python
from loop import (
    LoopOrchestrator, Memory, GeneratorAgent,
    EvaluatorAgent, BudgetGate, Finding, Status,
)

memory = Memory()
memory.save_finding(Finding(id="t1", text="Implement feature X", status=Status.PENDING))

generator = GeneratorAgent()
evaluator = EvaluatorAgent()
evaluator.add_rule("always_pass", lambda f, d, w: {"passed": True, "detail": "ok"})
budget = BudgetGate(per_run=10.0, per_turn=0.5, daily=100.0)

orchestrator = LoopOrchestrator(memory, generator, evaluator, budget)

# Run one turn
orchestrator.run_turn("Your template text here.")
# Returns True (work done) or False (nothing to process)

# Run until idle
for _ in range(10):
    if not orchestrator.run_turn("Your template text"):
        break
```

Automatically handles:
- **Budget gates** before/during each phase
- **Goal stop conditions** (run:cmd checks)
- **Human gates** (pauses for review on NEEDS_REVIEW findings)
- **Auto-archive** approved findings, **auto-reject** failed drafts

## Pitfalls

- **`add_rule()` signature:** `lambda finding, draft, worktree: {"passed": bool, "detail": str}` — all three args are mandatory.
- **`has_structure()`** requires `"# "` (Markdown heading) in the draft.
- **`execute()` is disabled** by default (`executor=None`). Set a callable first.
- **Connectors** must be passed to `memory.load_findings(connectors=[...])` — not auto-registered.
- **Smart /goal stop condition** executes `run:cmd` via `subprocess`. Goal dict format:
  ```python
  {"text": "...", "rules": [{"type": "run:cmd", "cmd": "pytest"}]}
  ```
- **BudgetGates are independent** — all three must pass, not just one.
- **Human gates** only affect `NEEDS_REVIEW` findings, not `REJECT` findings.

## Running tests

```bash
cd ~/hermes/loop
python test_loop.py
```

24 tests covering: Finding serialization, Memory persistence, Connector stubs, EvaluatorAgent rules/execute, GeneratorAgent worktrees/cost tracking, BudgetGate boundaries, full orchestrator round-trip.

## Directory structure

```
~/hermes/loop/
├── loop.py           # Framework core
├── test_loop.py      # 24 unit tests
├── inbox/            # Pending findings (JSON)
├── state/            # Archived results + state
├── worktrees/        # Isolated work directories
└── README.md         # This file
```

## Quotes

> "Build the loop, but build it like someone who intends to stay the engineer, not just the person who presses go."  
> — Addy Osmani

> "The loop is a faithful multiplier of its builder — a multiplier is exactly as valuable (and as dangerous) as the judgment fed into it."

## License

MIT.
