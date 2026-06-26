from app.doctor import DoctorCheck, format_doctor_report, run_doctor


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
        )
    }

    assert checks["state_root"].ok is True
    assert checks["openai_key"].ok is True
    assert checks["anthropic_key"].ok is False
    assert checks["gateway_token"].ok is True
    assert checks["nltk_stopwords"].ok is True
    assert checks["nltk_punkt_tab"].ok is True
