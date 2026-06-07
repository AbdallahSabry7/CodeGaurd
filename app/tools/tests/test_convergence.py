# app/services/tests/test_convergence.py
from convergence import score_report, compare_reports, ConvergenceController

def _report(solid=0, clean=0, complexity=0, severity="HIGH"):
    return {
        "solid_violations": [{"severity": severity, "confidence": 100} for _ in range(solid)],
        "clean_code_violations": [{"severity": severity, "confidence": 100} for _ in range(clean)],
        "complexity_findings": [{"improvable": True} for _ in range(complexity)],
    }

def test_clean_report_is_clean():
    assert score_report(_report()).is_clean()

def test_improvement_passes():
    assert compare_reports(_report(solid=3), _report(solid=1)).passed

def test_plateau_fails():
    r = _report(solid=2)
    assert not compare_reports(r, r).passed          # identical → no gain

def test_regression_fails():
    assert not compare_reports(_report(solid=1), _report(solid=3)).passed

def test_controller_finalizes_when_clean():
    assert ConvergenceController().decide(history=[0.0], loops=0) == "finalize"

def test_controller_continues_on_real_gain():
    assert ConvergenceController().decide(history=[10.0, 4.0], loops=1) == "continue"