#!/usr/bin/env python3
"""Lint Nova Caelum plan Markdown without project dependencies."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


MODULE_RE = re.compile(r"^(M\d+)\b")
TASK_RE = re.compile(r"^(T\d+(?:\.\d+)+)\b")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
NAMESPACE_RE = re.compile(
    r"\*\*External-id namespace:\*\*\s*`([^`]*)`", re.IGNORECASE
)

FIELD_NAMES = (
    "task_id",
    "external_id",
    "Owner",
    "Summary",
    "Blocked by",
    "Path",
    "Serves",
    "Acceptance criterion",
    "Budget",
    "Interfaces",
    "Note",
)
_FIELD_ALTERNATION = "|".join(re.escape(name) for name in FIELD_NAMES)
FIELD_RE = re.compile(
    rf"^\s*-\s+\*\*(?P<name>{_FIELD_ALTERNATION}):\*\*\s*(?P<value>.*)$"
)

CRITERION_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Z]\d+)(?![A-Za-z0-9_]|(?:\.\d))"
)
TASK_NUMBER_RE = re.compile(r"(?<!\w)(T\d+(?:\.\d+)+)(?!\w|(?:\.\d))")
SECTION_REFERENCE_RE = re.compile(r"(?<!\w)(§\d+(?:\.\d+)*)(?!\w|(?:\.\d))")
ACRONYM_RE = re.compile(r"(?<!\w)[\w-]*[A-Z]{2,}[\w-]*(?!\w)")


@dataclass(frozen=True, order=True)
class Violation:
    """One deterministic, user-facing lint finding."""

    line: int
    code: str
    target: str
    message: str


@dataclass
class TaskBlock:
    """A recoverable level-four task block and its parsed field markers."""

    label: str
    line: int
    module: str | None
    fields: dict[str, list[tuple[str, int]]]

    def first(self, field_name: str) -> tuple[str, int] | None:
        values = self.fields.get(field_name)
        return values[0] if values else None


def _heading(line: str) -> tuple[int, str] | None:
    match = HEADING_RE.match(line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _plain_content(value: str) -> str:
    """Remove common inline Markdown decoration for emptiness checks."""

    undecorated = re.sub(r"<!--.*?-->", "", value)
    undecorated = re.sub(r"[`*_~]", "", undecorated)
    undecorated = re.sub(r"^\s*>+\s*", "", undecorated)
    return undecorated.strip()


def _code_span_content(value: str) -> str:
    stripped = value.strip()
    while len(stripped) >= 2 and stripped.startswith("`") and stripped.endswith("`"):
        stripped = stripped[1:-1].strip()
    return stripped


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _summary_violations(task: TaskBlock, summary: str, line: int) -> Iterable[Violation]:
    classified_ranges: list[tuple[int, int]] = []
    patterns = (
        (
            "S6_CRITERION_CODE",
            CRITERION_RE,
            "criterion code",
        ),
        (
            "S6_TASK_NUMBER",
            TASK_NUMBER_RE,
            "task number",
        ),
        (
            "S6_SECTION_REFERENCE",
            SECTION_REFERENCE_RE,
            "section reference",
        ),
    )
    for code, pattern, family in patterns:
        for match in pattern.finditer(summary):
            classified_ranges.append(match.span())
            yield Violation(
                line,
                code,
                task.label,
                f"Summary contains {family} {match.group(1)!r}; use plain English.",
            )

    for match in ACRONYM_RE.finditer(summary):
        if any(_ranges_overlap(match.span(), span) for span in classified_ranges):
            continue
        yield Violation(
            line,
            "S6_ACRONYM_JARGON",
            task.label,
            f"Summary contains acronym or identifier jargon {match.group(0)!r}; use plain English.",
        )


def _parse_tasks(lines: Sequence[str]) -> tuple[list[TaskBlock], list[Violation]]:
    tasks: list[TaskBlock] = []
    violations: list[Violation] = []
    current_module: str | None = None

    task_starts: list[tuple[int, str, int, str | None]] = []
    for index, line in enumerate(lines):
        parsed_heading = _heading(line)
        if parsed_heading is None:
            continue
        level, title = parsed_heading
        module_match = MODULE_RE.match(title)
        task_match = TASK_RE.match(title)

        if module_match:
            module_label = module_match.group(1)
            if level != 2:
                violations.append(
                    Violation(
                        index + 1,
                        "S1_MODULE_LEVEL",
                        module_label,
                        f"Module-like heading is level {level}; required level is 2.",
                    )
                )
                current_module = None
            else:
                current_module = module_label
        elif level == 2:
            current_module = None

        if not task_match:
            continue

        task_label = task_match.group(1)
        if level != 4:
            violations.append(
                Violation(
                    index + 1,
                    "S2_TASK_LEVEL",
                    task_label,
                    f"Task-like heading is level {level}; required level is 4.",
                )
            )
            continue

        if current_module is None:
            violations.append(
                Violation(
                    index + 1,
                    "S2_TASK_OUTSIDE_MODULE",
                    task_label,
                    "Level-4 task heading has no preceding valid level-2 module heading.",
                )
            )
        task_starts.append((index, task_label, index + 1, current_module))

    for position, (start, label, line_number, module) in enumerate(task_starts):
        end = len(lines)
        for index in range(start + 1, len(lines)):
            parsed_heading = _heading(lines[index])
            if parsed_heading is None:
                continue
            _, title = parsed_heading
            if MODULE_RE.match(title) or TASK_RE.match(title):
                end = index
                break

        fields: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for index in range(start + 1, end):
            field_match = FIELD_RE.match(lines[index])
            if field_match:
                fields[field_match.group("name")].append(
                    (field_match.group("value"), index + 1)
                )
        tasks.append(TaskBlock(label, line_number, module, dict(fields)))

    return tasks, violations


parse_tasks = _parse_tasks  # public alias — node_gates.check_specifying (T4.5) reuses the one task-block parser


def lint_text(text: str) -> list[Violation]:
    """Return all applicable plan-format violations in stable source order."""

    lines = text.splitlines()
    tasks, violations = _parse_tasks(lines)

    namespace_match = NAMESPACE_RE.search(text)
    prefix = namespace_match.group(1).strip() if namespace_match else None
    if not prefix:
        violations.append(
            Violation(
                1,
                "S4_NAMESPACE_MISSING",
                "document",
                "Plan metadata must define a non-empty **External-id namespace:** code span.",
            )
        )

    external_ids: dict[str, list[TaskBlock]] = defaultdict(list)
    for task in tasks:
        for field_name in FIELD_NAMES:
            if field_name not in task.fields:
                violations.append(
                    Violation(
                        task.line,
                        "S3_MISSING_FIELD",
                        task.label,
                        f"Task block is missing required field marker {field_name!r}.",
                    )
                )

        external_id_field = task.first("external_id")
        if external_id_field is None:
            violations.append(
                Violation(
                    task.line,
                    "S4_EXTERNAL_ID_MISSING",
                    task.label,
                    "external_id field is required.",
                )
            )
        else:
            raw_external_id, external_id_line = external_id_field
            external_id = _code_span_content(raw_external_id)
            if not external_id:
                violations.append(
                    Violation(
                        external_id_line,
                        "S4_EXTERNAL_ID_EMPTY",
                        task.label,
                        "external_id is empty after Markdown code-span stripping.",
                    )
                )
            else:
                external_ids[external_id].append(task)
                if prefix and not external_id.startswith(prefix):
                    violations.append(
                        Violation(
                            external_id_line,
                            "S4_EXTERNAL_ID_PREFIX",
                            task.label,
                            f"external_id {external_id!r} must begin with inferred prefix {prefix!r}.",
                        )
                    )

        path_field = task.first("Path")
        if path_field is not None and not _plain_content(path_field[0]):
            violations.append(
                Violation(
                    path_field[1],
                    "S5_PATH_EMPTY",
                    task.label,
                    "Path is empty after trimming Markdown decoration and whitespace.",
                )
            )

        acceptance_field = task.first("Acceptance criterion")
        if acceptance_field is not None and not _plain_content(acceptance_field[0]):
            violations.append(
                Violation(
                    acceptance_field[1],
                    "S5_ACCEPTANCE_EMPTY",
                    task.label,
                    "Acceptance criterion is empty after trimming Markdown decoration and whitespace.",
                )
            )

        summary_field = task.first("Summary")
        if summary_field is not None:
            violations.extend(_summary_violations(task, *summary_field))

    for external_id, matching_tasks in external_ids.items():
        if len(matching_tasks) < 2:
            continue
        labels = ", ".join(task.label for task in matching_tasks)
        for task in matching_tasks:
            field = task.first("external_id")
            assert field is not None
            violations.append(
                Violation(
                    field[1],
                    "S4_EXTERNAL_ID_DUPLICATE",
                    task.label,
                    f"external_id {external_id!r} is duplicated by tasks {labels}.",
                )
            )

    return sorted(violations)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lint one Nova Caelum plan Markdown file.")
    parser.add_argument("plan", type=Path, help="Markdown plan to lint")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        text = args.plan.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"ERROR: cannot read {args.plan}: {exc}", file=sys.stderr)
        return 2

    violations = lint_text(text)
    if not violations:
        print(f"CLEAN: {args.plan}: no plan-format violations")
        return 0

    for violation in violations:
        print(
            f"[{violation.code}] {violation.target}: {violation.message} "
            f"(line {violation.line})"
        )
    print(f"FOUND: {len(violations)} plan-format violation(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
