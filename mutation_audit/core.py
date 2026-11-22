"""PR-scoped AST mutation testing gate."""
from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mutant:
    """A single AST-derived mutation of one function."""

    function: str
    description: str
    tree: ast.Module


@dataclass
class AuditResult:
    """Outcome of a mutation audit."""

    passed: bool
    killed: int = 0
    survivors: list[str] = field(default_factory=list)
    tested_functions: list[str] = field(default_factory=list)


class _Mutator(ast.NodeTransformer):
    """Generate one mutant per supported node, tagged via node annotations."""

    def __init__(self) -> None:
        self.mutants: list[tuple[str, ast.Module]] = []
        self.current: ast.AST | None = None

    def _emit(self, description: str) -> None:
        self.mutants.append((description, _clone(self.current)))

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        flips = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
        if type(node.op) in flips:
            orig = type(node.op).__name__
            node.op = flips[type(node.op)]()
            self._emit(f"binop {orig} flipped in {self._name()}")
            node.op = flips[type(node.op)]()  # restore to original class op
        return self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        swaps = {ast.Lt: ast.Gt, ast.Gt: ast.Lt, ast.LtE: ast.GtE, ast.GtE: ast.LtE, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
        for i, op in enumerate(node.ops):
            if type(op) in swaps:
                orig = type(op).__name__
                node.ops[i] = swaps[type(op)]()
                self._emit(f"compare {orig} inverted in {self._name()}")
                node.ops[i] = swaps[type(op)]()
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            node.value += 1
            self._emit(f"constant bumped in {self._name()}")
            node.value -= 1
        return node

    def visit_Expr(self, node: ast.Expr) -> ast.AST:
        if not isinstance(node.value, ast.Constant):
            self._emit(f"statement removed in {self._name()}")
        return self.generic_visit(node)

    def _name(self) -> str:
        return getattr(self.current, "name", "<module>")


def _clone(node: ast.AST | None) -> ast.Module:
    """Deep-copy an AST via round-trip through source."""
    assert node is not None
    return ast.parse(ast.unparse(node))


def generate_mutants(source: str) -> list[Mutant]:
    """Return typed semantic mutants for each function in *source*."""
    tree = ast.parse(source)
    out: list[Mutant] = []
    for fn in [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        m = _Mutator()
        m.current = fn
        m.visit(fn)
        for description, mutated_fn in m.mutants:
            wrapper = ast.Module(body=[mutated_fn], type_ignores=[])
            ast.fix_missing_locations(wrapper)
            out.append(Mutant(function=fn.name, description=description, tree=wrapper))
    return out


def _candidate_tests(root: Path, func_names: set[str]) -> list[Path]:
    """Lightweight code-to-test edge: tests referencing a changed function name."""
    tests: list[Path] = []
    for p in root.rglob("test_*.py"):
        try:
            src = p.read_text()
        except OSError:
            continue
        if any(name in src for name in func_names):
            tests.append(p)
    return tests


def _run(module_path: Path, source: str, tests: list[Path], root: Path) -> bool:
    """Run candidate tests against mutant source. Return True iff a test failed (killed)."""
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        patched = module_path.read_text()
        target = td_path / module_path.name
        target.write_text(source)
        for t in tests:
            rel = t.relative_to(root)
            dst = td_path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(t.read_text().replace(module_path.stem, str(target.with_suffix(""))) if False else t.read_text())
        env = {"PYTHONPATH": str(td_path)}
        for t in tests:
            rel = t.relative_to(root)
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", str(rel)],
                cwd=td_path,
                capture_output=True,
                text=True,
                env={**__import__("os").environ, **env},
            )
            if proc.returncode != 0:
                return True
        return False


def audit(repo: str, changed: list[str]) -> AuditResult:
    """Mutate changed functions and verify covering tests kill every mutant."""
    root = Path(repo).resolve()
    survivors: list[str] = []
    killed = 0
    tested: list[str] = []
    for rel in changed:
        path = (root / rel).resolve()
        if not path.is_file() or path.suffix != ".py":
            continue
        source = path.read_text()
        mutants = generate_mutants(source)
        if not mutants:
            continue
        names = {m.function for m in mutants}
        tested.extend(sorted(names))
        tests = _candidate_tests(root, names)
        for mut in mutants:
            mutant_src = ast.unparse(mut.tree)
            if _run(path, mutant_src, tests, root):
                killed += 1
            else:
                survivors.append(f"{rel}:{mut.function}: {mut.description}")
    return AuditResult(passed=not survivors, killed=killed, survivors=survivors, tested_functions=sorted(set(tested)))
