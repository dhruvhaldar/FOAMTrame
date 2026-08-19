from scripts.codeaudit_gate import blocks_build, collect_findings


def test_codeaudit_gate_flattens_and_sorts_findings():
    scan_result = {
        "file_security_info": {
            0: {
                "FilePath": "z.py",
                "sast_result": {
                    8: {"line": 8, "severity": "High", "validation": "unsafe"}
                },
            },
            1: {
                "FilePath": "a.py",
                "sast_result": {
                    3: {"line": 3, "severity": "Low", "validation": "review"}
                },
            },
        }
    }

    findings = collect_findings(scan_result)

    assert [(item["path"], item["line"]) for item in findings] == [
        ("a.py", 3),
        ("z.py", 8),
    ]
    assert blocks_build(findings[0], "medium") is False
    assert blocks_build(findings[1], "medium") is True
