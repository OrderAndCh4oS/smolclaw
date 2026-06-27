import os

from app.command_runner import CommandResult
from app.doctor import DoctorCheck, format_doctor_report, run_doctor
from app.runtime_config import RuntimeAdapterConfig


class FakeCommandRunner:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def run(self, args, *, cwd=None, input_text=None, timeout=600, network_access=False):
        self.calls.append({
            "args": args,
            "cwd": cwd,
            "input_text": input_text,
            "timeout": timeout,
        })
        return self.result


def test_format_doctor_report_marks_warnings_and_nltk_fix():
    report = format_doctor_report([
        DoctorCheck("state_root", True, "state root writable"),
        DoctorCheck("nltk_stopwords", False, "NLTK stopwords corpus available"),
    ])

    assert "ok: state_root" in report
    assert "warn: nltk_stopwords" in report
    assert "nltk.download('stopwords')" in report


def test_run_doctor_checks_workspace_and_environment(temp_dir):
    checks = {
        check.name: check
        for check in run_doctor(
            temp_dir,
            env={"OPENAI_API_KEY": "openai", "SMOLCLAW_GATEWAY_TOKEN": "gateway"},
            nltk_resource_checker=lambda _resource: True,
            adapter_config=RuntimeAdapterConfig(),
        )
    }

    assert checks["state_root"].ok is True
    assert checks["openai_key"].ok is True
    assert checks["anthropic_key"].ok is False
    assert checks["gateway_token"].ok is True
    assert checks["nltk_stopwords"].ok is True
    assert checks["nltk_punkt_tab"].ok is True
    assert checks["command_provider"].message == "command provider: subprocess"


def test_run_doctor_reports_docker_sandbox_state(temp_dir):
    with open(os.path.join(temp_dir, "package.json"), "w", encoding="utf-8") as handle:
        handle.write("{}")
    runner = FakeCommandRunner(CommandResult(
        args=["docker", "version"],
        returncode=127,
        stderr="[Errno 2] No such file or directory: 'docker'",
    ))

    checks = {
        check.name: check
        for check in run_doctor(
            temp_dir,
            env={},
            nltk_resource_checker=lambda _resource: True,
            command_runner=runner,
            adapter_config=RuntimeAdapterConfig.from_dict({
                "adapters": {"command": {"provider": "docker"}},
            }),
        )
    }

    assert checks["command_provider"].message == "command provider: docker"
    assert checks["docker_daemon"].ok is False
    assert "Docker sandbox unavailable" in checks["docker_daemon"].message
    assert checks["sandbox_image"].ok is False
    assert "project toolchains: node" in checks["sandbox_image"].message
    assert checks["sandbox_network"].ok is True
    assert runner.calls[0]["args"] == ["docker", "version", "--format", "{{.Server.Version}}"]
