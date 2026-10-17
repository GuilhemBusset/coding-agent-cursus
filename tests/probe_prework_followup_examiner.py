"""Follow-up examination: reuse the independent examiner cases on the real files."""
from pathlib import Path
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def run_case(filename, method):
    namespace = runpy.run_path(str(ROOT / 'tests' / filename))
    namespace['Probe'](method).debug()


def test_D1_A4_installation_page():
    run_case('probe_prework_page_examiner.py', 'test_D1_A4_install_coverage_and_sources')


def test_D2_A1_tools_versions_network_auth_and_either_agent():
    run_case('probe_prework_examiner.py', 'test_D2_A1_single_agents')


def test_D2_bootstrap_failure_has_summary():
    run_case('probe_prework_examiner.py', 'test_D2_bootstrap_exit_one_summary')


def test_D3_actual_push_fork_and_cleanup():
    run_case('probe_prework_examiner.py', 'test_D3_real_push_and_fork')


def test_D4_reading_selection():
    namespace = runpy.run_path(str(ROOT / 'tests/probe_prework_reading_examiner.py'))
    namespace['test_D4_readings_and_selected_chapters']()


def test_A2_failure_status_and_secret_suppression():
    run_case('probe_prework_examiner.py', 'test_A2_failed_auth_and_smoke_hide_secrets')


def test_A2_shell_syntax_and_shellcheck():
    script = 'sessions/01-fundamentals/exercises/check-setup.sh'
    for command in ([ 'bash', '-n', script ],
                    [ 'uv', 'run', '--no-project', '--with', 'shellcheck-py==0.10.0.1',
                      'shellcheck', script ]):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr


def test_A3_agent_platform_evidence_and_limitations():
    run_case('probe_prework_page_examiner.py', 'test_A3_agent_part_explicit_untested_platforms')
