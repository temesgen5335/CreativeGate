# CreativeGate — agent/developer governance

CreativeGate is a simulation-first evaluation funnel for creative artifacts:
*evaluate before you spend, and make every cheap evaluator earn its trust by
continuous calibration against the expensive ones.*

**Before working, read the governance docs in `.claude/` — in this order:**

1. `.claude/context.md` — problem statement, vision, product surfaces, roadmap,
   and what is explicitly out of scope.
2. `.claude/rules.md` — **non-negotiable** design principles and safety rails
   (uncalibrated rungs carry zero fusion weight; validity is framework-stamped,
   never self-asserted; keyless mode always works; no AI attribution in
   commits). Changes violating these are rejected regardless of quality.
3. `.claude/agent.md` — setup, repository map, data flow, and recipes
   (add a rung, add a provider, v0.2 starting points).
4. `.claude/memory.md` — build history, design decisions (D1–D12), measured
   regression baselines, and gotchas. **Append your own non-obvious decisions
   to its decision log.**

## Quick facts

- Python ≥ 3.11, managed with `uv`: `uv venv && uv pip install -e ".[dev]"`
- Verify: `uv run pytest` (45 tests, ~2s, fully offline — must stay green)
- See it work: `uv run creativegate demo`
- No API keys required anywhere in the core path; `OPENAI_API_KEY` optionally
  upgrades the judge rung.
- `src/creativegate/schemas.py` is the stable contract; the calibration
  harness (`src/creativegate/calibration/harness.py`) is the sole source of
  fusion weights and validity claims.
- Commits: logically separated, imperative subject, body explains why,
  **no AI attribution of any kind** (charter requirement).
