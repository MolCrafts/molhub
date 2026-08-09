"""Execute every Python fence in the documentation, or report its explicit skip."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
FENCE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
ANNOTATED = re.compile(r"<!--\s*test:\s*([^>]+?)\s*-->\s*```python\s*\n(.*?)```", re.DOTALL)


def test_documented_python_examples() -> None:
    executed: list[str] = []
    skipped: list[str] = []
    failures: list[str] = []

    for path in sorted(DOCS.rglob("*.md")):
        source = path.read_text(encoding="utf8")
        fences = FENCE.findall(source)
        examples = ANNOTATED.findall(source)
        assert len(fences) == len(examples), (
            f"{path.relative_to(ROOT)} has an unclassified Python fence; "
            "add <!-- test: exec --> or <!-- test: skip reason -->"
        )
        for index, (directive, code) in enumerate(examples, start=1):
            label = f"{path.relative_to(ROOT)}:{index}"
            if directive.strip().startswith("skip"):
                skipped.append(f"{label} ({directive.strip()})")
                continue
            assert directive.strip() == "exec", f"Unknown docs test directive at {label}"
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                executed.append(label)
            else:
                failures.append(f"{label}\n{result.stdout}{result.stderr}")

    print(f"docs Python: {len(executed)} executed, {len(skipped)} skipped")
    for item in skipped:
        print(f"SKIP {item}")
    assert executed, "No executable Python documentation examples were found"
    assert not failures, "\n\n".join(failures)
