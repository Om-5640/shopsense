#!/usr/bin/env python3
"""
CI/CD eval runner script.

Usage:
    python scripts/run_evals.py              # quick eval + JSON report
    python scripts/run_evals.py --full       # full suite + HTML report
    python scripts/run_evals.py --ci         # strict CI gate (exits non-zero on fail)
    python scripts/run_evals.py --tournament # tournament mode

Exit codes:
    0 = passed
    1 = eval failure / regression
    2 = invalid arguments
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
