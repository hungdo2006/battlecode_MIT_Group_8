"""Functional frontend check using the same Node prerequisite as baseline CI."""
from pathlib import Path
import subprocess


def test_public_results_bracket_and_match_history():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "scripts/check_public_results_rendering.cjs"],
                   cwd=root, check=True, capture_output=True, text=True, timeout=15)
