"""Independent submission witness using the pre-existing turn-in sandbox, not the new test."""
import importlib.util
import json
from pathlib import Path
import shutil

from test_p01_homework import CONTRACTS, PACK, checker, read_instance, single_leg_candidate


def test_real_sheet_payload_and_checker_verdict_reach_only_the_fork(tmp_path):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location('turn_in_harness_45', root / 'tests/turn_in/test_turn_in_script.py')
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    s = harness.Sandbox(tmp_path, permission='READ', fork_origin=True)
    work = s.repo / s.exercises
    shutil.copytree(PACK.parent, work, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    plan = single_leg_candidate(read_instance(PACK), True)
    payload = json.dumps(plan)
    (work / 'homework-p01/solution.json').write_text(payload, encoding='utf-8')
    verdict = checker(work / 'homework-p01').stdout
    tags = {line.split(':', 1)[0] for line in verdict.splitlines()} & CONTRACTS
    assert tags == {'optimality'}, verdict
    notes = ('# Offline rehearsal\n\n## Part 1\nSampling and strawberry: example observations.\n'
             '## Part 2\nTokens are sampled. Replies are generated. Check the result.\n'
             '## Part 3\n' + verdict)
    (work / 'home-notes.md').write_text(notes, encoding='utf-8')
    course_before = s.git('show-ref', cwd=s.remotes[s.course]).stdout
    result = s.run('01')
    assert f'Running {s.exercises}/turn-in-check.sh' in result.stderr
    assert verdict.strip() in result.stdout + result.stderr
    assert f'https://github.com/{s.fork_name}/tree/{s.branch}' in result.stdout
    assert f'Compare with the course: https://github.com/{s.course}/compare/main...stud:{s.branch}' in result.stdout
    assert s.git('show-ref', cwd=s.remotes[s.course]).stdout == course_before
    assert s.git('show', f'{s.branch}:{s.exercises}/home-notes.md', cwd=s.remotes[s.fork_name]).stdout == notes
    assert s.git('show', f'{s.branch}:{s.exercises}/homework-p01/solution.json', cwd=s.remotes[s.fork_name]).stdout == payload
    assert s.git('log', '-1', '--format=%s', s.branch, cwd=s.remotes[s.fork_name]).stdout.strip() == 'Turn in session 01 homework (stud)'
    s.assert_confined(s.fork_name)
