"""Turn failed JUnit XML test cases into GitHub error annotations.

Usage: python annotate_test_failures.py <results-dir> [<fallback-log>]

Annotations show up on the workflow run summary and the PR checks, so test
failures (e.g. the OCR text an assertion saw) are visible without digging
through the raw job log.
"""
import glob
import os
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main() -> int:
    root = sys.argv[1]
    files = glob.glob(os.path.join(root, "**", "*.xml"), recursive=True)
    failures = 0
    for path in files:
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        for case in tree.iter("testcase"):
            for tag in ("failure", "error"):
                for node in case.findall(tag):
                    failures += 1
                    name = f"{case.get('classname', '').rsplit('.', 1)[-1]}.{case.get('name')}"
                    body = (node.text or node.get("message") or "").strip()
                    print(f"::error title=Test failed: {name}::{esc(body[:3500])}")
    if not files and len(sys.argv) > 2 and os.path.exists(sys.argv[2]):
        with open(sys.argv[2], encoding="utf-8", errors="replace") as fh:
            tail = fh.read()[-3500:]
        print(f"::error title=No test results (log tail)::{esc(tail)}")
    print(f"{len(files)} result file(s), {failures} failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
