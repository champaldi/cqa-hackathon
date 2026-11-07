"""Проверка зон: PR меняет только файлы своей роли.

Роль определяется по префиксу ветки или точному имени frontend.
Владельцы файлов описаны в таблице OWNERS.
Запуск: python scripts/check_scope.py --branch qa/gold-set --base origin/main

Коды выхода: 0 нарушений нет, 1 есть чужие файлы, 2 проверку выполнить не удалось.
"""

import argparse
import subprocess
import sys
from collections.abc import Iterable, Sequence
from typing import Final

CONTRACT: Final = "contract"
FRONTEND: Final = "frontend"
ROLES: Final = frozenset({"backend", "llm", "ui", "qa"})
NOBODY: Final[frozenset[str]] = frozenset()
DEFAULT_OWNERS: Final = frozenset({"backend"})

# Первое совпадение выигрывает. Шаблон с / на конце это папка, остальные это точный путь.
# Всё, чего нет в таблице (CI, зависимости, scripts/, .gitignore), относится к DEFAULT_OWNERS.
OWNERS: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    ("backend/app/contracts.py", NOBODY),
    ("frontend/api.js", NOBODY),
    ("AGENTS.md", NOBODY),
    ("CLAUDE.md", NOBODY),
    ("frontend/checklist/", frozenset({"qa", FRONTEND})),
    ("frontend/", frozenset({"ui", FRONTEND})),
    ("backend/app/evaluator/", frozenset({"llm"})),
    ("backend/app/scoring/", frozenset({"qa"})),
    ("backend/tests/evaluator/", frozenset({"llm", "qa"})),
    ("backend/tests/", frozenset({"backend", "qa"})),
    ("backend/", frozenset({"backend"})),
    ("eval/", frozenset({"qa"})),
    ("config/", frozenset({"qa"})),
    ("docs/", frozenset({"qa"})),
    ("README.md", frozenset({"qa"})),
)


def role_of(branch: str) -> str | None:
    if branch == FRONTEND:
        return FRONTEND
    prefix, _, name = branch.partition("/")
    known = prefix in ROLES or prefix == CONTRACT
    return prefix if known and name else None


def owners_of(path: str) -> frozenset[str]:
    for pattern, owners in OWNERS:
        if path == pattern or (pattern.endswith("/") and path.startswith(pattern)):
            return owners
    return DEFAULT_OWNERS


def violations(branch: str, paths: Iterable[str]) -> list[str]:
    role = role_of(branch)
    if role is None:
        allowed = ", ".join(f"{prefix}/" for prefix in sorted({*ROLES, CONTRACT}))
        raise ValueError(
            f"ветка {branch!r} без роли, нужен префикс: {allowed} или точная ветка {FRONTEND!r}"
        )
    if role == CONTRACT:
        return []
    return [path for path in paths if role not in owners_of(path)]


def changed_files(base: str) -> list[str]:
    if base.startswith("-"):
        raise ValueError(f"недопустимое значение --base: {base!r}")
    # -z отдаёт пути без кавычек и экранирования, иначе кириллица в имени обходит таблицу владельцев.
    command = ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...HEAD"]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git diff не выполнился: {result.stderr.strip()}")
    return [path for path in result.stdout.split("\0") if path]


def report(branch: str, foreign: Sequence[str]) -> str:
    files = "\n".join(f"  {path}" for path in foreign)
    return (
        f"Ветка {branch!r} меняет файлы вне зоны своей роли:\n{files}\n"
        "Уберите эти правки из PR. Если чужая правка нужна, опишите её в PR: её сделает владелец зоны."
    )


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Проверяет, что PR меняет только файлы своей роли.")
    parser.add_argument("--branch", required=True, help="ветка PR, например qa/gold-set")
    parser.add_argument("--base", required=True, help="с чем сравнивать, например origin/main")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        paths = changed_files(args.base)
        foreign = violations(args.branch, paths)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Проверка зон не выполнена: {error}", file=sys.stderr)
        return 2
    if foreign:
        print(report(args.branch, foreign), file=sys.stderr)
        return 1
    print(f"Зоны в порядке, файлов в PR: {len(paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
