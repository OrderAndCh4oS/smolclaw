"""Command classification policy for agent command tools."""

from __future__ import annotations

import shlex
from dataclasses import dataclass


DENIED_COMMAND_TOKENS = frozenset({
    "rm",
    "mv",
    "install",
    "add",
    "checkout",
    "clean",
    "reset",
    "restore",
    "switch",
})


@dataclass(frozen=True)
class CommandPolicyClassifier:
    denied_tokens: frozenset[str] = DENIED_COMMAND_TOKENS

    def is_allowed(self, args: list[str]) -> tuple[bool, str]:
        if any(token in self.denied_tokens for token in args):
            return False, "contains a denied token"
        if not args:
            return False, "command is required"
        if args[0] == "git":
            return len(args) > 1 and args[1] in {"status", "diff", "log", "show", "branch"}, "git command must be read-only"
        if args[0] == "pytest":
            return True, ""
        if args[:3] == ["python", "-m", "pytest"]:
            return True, ""
        if args[0] in {"npm", "pnpm", "yarn", "bun"}:
            return self.package_command_allowed(args)
        if args[0] == "cargo":
            return len(args) > 1 and args[1] in {"test", "check"}, "cargo command must be test or check"
        if args[:2] == ["go", "test"]:
            return True, ""
        return False, f"unsupported command family: {args[0]}"

    def is_approval_bypassable(self, args: list[str]) -> bool:
        if args[0] in {"npm", "pnpm", "yarn", "bun"} and len(args) > 1:
            return args[1] in {"install", "i", "add", "view"}
        if args[:2] == ["node", "-e"]:
            return True
        return False

    def may_mutate(self, command: str) -> bool:
        try:
            args = shlex.split(command)
        except ValueError:
            return True
        if not args:
            return False
        if any(marker in command for marker in (">", ">>", "2>", ">|")):
            return True
        if any(token in self.denied_tokens for token in args):
            return True
        if args[0] == "git":
            return not (len(args) > 1 and args[1] in {"status", "diff", "log", "show", "branch"})
        if args[0] in {"pytest", "cargo"}:
            return False
        if args[:3] == ["python", "-m", "pytest"]:
            return False
        if args[:2] == ["go", "test"]:
            return False
        if args[0] in {"npm", "pnpm", "yarn", "bun"}:
            return not self.package_command_is_read_only(args)
        return True

    def package_command_allowed(self, args: list[str]) -> tuple[bool, str]:
        if len(args) >= 2 and args[1] == "test":
            return True, ""
        if len(args) >= 3 and args[1] == "run" and not args[2].startswith("-"):
            return True, ""
        return False, f"{args[0]} command must be test or run <script>"

    def package_command_is_read_only(self, args: list[str]) -> bool:
        if len(args) >= 2 and args[1] == "test":
            return True
        return len(args) >= 3 and args[1] == "run" and args[2] in {"test", "check", "lint"}
