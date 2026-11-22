# mutation-audit

PR-scoped mutation gate. delta-verify asks *did a test file change?*; mutation-audit asks *would those tests kill a regression in the changed function?*

## Purpose
Coverage and green CI prove execution, not detection. A PR can add a test that calls a changed function but asserts nothing meaningful. mutation-audit mutates only changed functions via AST rewriting, runs only tests that import them, and fails if any mutant survives.

## Usage
```python
from mutation_audit import audit

result = audit(repo_path, changed=["pkg/calc.py"])
assert result.passed, result.survivors
```
CLI: `python -m mutation_audit --repo . --changed pkg/calc.py`

## Design
1. Parse each changed file, extract function ASTs (the delta-verify code graph boundary).
2. Generate typed semantic mutants: operator flips (`+`/`-`/`*`), constant tweaks (n -> n+1), branch inversions (`<`/`>`), statement removal.
3. Discover candidate tests: test files whose source references the function name (lightweight dependency edge).
4. For each mutant, write a temp copy of the module, run pytest on the candidate tests, and mark the mutant killed iff any test fails.
5. A mutant that survives means the tests do not detect that behavioral change -> gate fails.

Novelty vs mutmut/cosmic-ray: those mutate whole repos and mutate at runtime/bytecode. This is PR-scoped, AST-typed, and reuses a coverage-derived test edge, so it is fast enough for CI.

Stdlib only (ast, subprocess, sys, pathlib). pytest is the test runner dependency.