"""Run the real static checker over the delivered entry points."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shellcheck_on_actual_student_entry_points():
    result = subprocess.run(['uv', 'run', '--no-project', '--with', 'shellcheck-py==0.10.0.1', 'shellcheck',
                             'setup/student/install.sh', 'setup/session-01-fundamentals.sh'],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
