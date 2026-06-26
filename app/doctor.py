from __future__ import annotations

import os
from dataclasses import dataclass

from app.definitions import build_workspace_paths


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str


def check_nltk_resource(resource: str) -> bool:
    try:
        import nltk

        nltk.data.find(resource)
        return True
    except LookupError:
        return False


def run_doctor(
    workspace_root: str | None = None,
    *,
    env: dict[str, str] | None = None,
    nltk_resource_checker=None,
) -> list[DoctorCheck]:
    paths = build_workspace_paths(workspace_root)
    env = env if env is not None else os.environ
    nltk_resource_checker = nltk_resource_checker or check_nltk_resource
    checks = [
        DoctorCheck(
            "state_root",
            _directory_writable(paths.state_root_dir),
            f"state root writable: {paths.state_root_dir}",
        ),
        DoctorCheck(
            "openai_key",
            bool(env.get("OPENAI_API_KEY")),
            "OPENAI_API_KEY configured" if env.get("OPENAI_API_KEY") else "OPENAI_API_KEY is not set",
        ),
        DoctorCheck(
            "anthropic_key",
            bool(env.get("ANTHROPIC_API_KEY")),
            "ANTHROPIC_API_KEY configured" if env.get("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY is not set",
        ),
        DoctorCheck(
            "nltk_stopwords",
            nltk_resource_checker("corpora/stopwords"),
            "NLTK stopwords corpus available",
        ),
        DoctorCheck(
            "nltk_punkt_tab",
            nltk_resource_checker("tokenizers/punkt_tab/english"),
            "NLTK punkt_tab tokenizer available",
        ),
        DoctorCheck(
            "gateway_token",
            bool(env.get("SMOLCLAW_GATEWAY_TOKEN")),
            "SMOLCLAW_GATEWAY_TOKEN configured" if env.get("SMOLCLAW_GATEWAY_TOKEN") else "SMOLCLAW_GATEWAY_TOKEN is not set",
        ),
    ]
    return checks


def format_doctor_report(checks: list[DoctorCheck]) -> str:
    lines = []
    for check in checks:
        status = "ok" if check.ok else "warn"
        lines.append(f"{status}: {check.name}: {check.message}")
    if any(not check.ok and check.name.startswith("nltk_") for check in checks):
        lines.append(
            "fix: python -c \"import nltk; "
            "nltk.download('stopwords'); nltk.download('punkt_tab')\""
        )
    return "\n".join(lines)


def _directory_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".doctor-write-test")
        with open(test_path, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(test_path)
        return True
    except OSError:
        return False
