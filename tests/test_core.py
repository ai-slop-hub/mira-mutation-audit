import os
import tempfile
from pathlib import Path

from mutation_audit.core import audit, generate_mutants


def _repo(files):
    d = tempfile.mkdtemp()
    for rel, content in files.items():
        p = Path(d) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_generate_mutants_produces_operator_and_constant_variants():
    mutants = generate_mutants("def add(a, b):\n    return a + b + 1\n")
    descs = [m.description for m in mutants]
    assert any("binop" in d for d in descs)
    assert any("constant" in d for d in descs)
    assert all(m.function == "add" for m in mutants)


def test_mutants_are_executable_python():
    for m in generate_mutants("def f(x):\n    if x > 0:\n        return x * 2\n    return 0\n"):
        compile(ast_unparse(m.tree), "<m>", "exec")


def ast_unparse(node):
    import ast
    return ast.unparse(node)


def test_strong_tests_kill_all_mutants():
    d = _repo({
        "calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": (
            "from calc import add\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
            "    assert add(-1, 1) == 0\n"
        ),
    })
    result = audit(d, ["calc.py"])
    assert result.passed, result.survivors
    assert result.killed >= 1


def test_vacuous_tests_let_mutants_survive():
    d = _repo({
        "calc.py": "def add(a, b):\n    return a + b\n",
        "tests/test_calc.py": (
            "from calc import add\n"
            "def test_add():\n"
            "    add(2, 3)\n"
        ),
    })
    result = audit(d, ["calc.py"])
    assert not result.passed
    assert result.survivors


def test_audit_skips_non_python_and_absent_paths():
    d = _repo({"README.md": "hi\n"})
    result = audit(d, ["README.md", "missing.py"])
    assert result.passed
    assert result.killed == 0
    assert result.tested_functions == []
