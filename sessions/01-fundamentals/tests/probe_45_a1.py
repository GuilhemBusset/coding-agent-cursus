"""Independent submission witness: the sheet's payload and verdict reach only the fork, byte for byte.

Uses the session-local sandbox (real git, hooks, turn-in.sh and checker; only gh faked) so no
code is loaded from outside the session (ADR 0001, test_self_contained.py).
"""
import json
import subprocess

from test_home_turn_in import COURSE, EXERCISES, FORK, HANDLE, git, sandbox
from test_p01_homework import CONTRACTS, PACK, checker, read_instance, single_leg_candidate


def test_real_sheet_payload_and_checker_verdict_reach_only_the_fork(tmp_path):
    env, bares = sandbox(tmp_path)
    clone = tmp_path / 'student'
    git('clone', '-q', f'https://github.com/{FORK}.git', clone, cwd=tmp_path, env=env)
    git('config', 'core.hooksPath', '.githooks', cwd=clone, env=env)
    work = clone / EXERCISES
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
    course, fork = bares[COURSE], bares[FORK]
    course_before = git('show-ref', cwd=course, env=env)
    result = subprocess.run(['bash', 'scripts/turn-in.sh', '01'], cwd=clone, env=env, text=True,
                            capture_output=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    branch = f'homework/s01/{HANDLE}'
    assert f'Running {EXERCISES}/turn-in-check.sh' in result.stderr
    assert verdict.strip() in result.stdout + result.stderr
    assert f'https://github.com/{FORK}/tree/{branch}' in result.stdout
    assert f'Compare with the course: https://github.com/{COURSE}/compare/main...{HANDLE}:{branch}' in result.stdout
    assert git('show-ref', cwd=course, env=env) == course_before
    shown = subprocess.run(['git', 'show', f'{branch}:{EXERCISES}/home-notes.md'], cwd=fork, env=env,
                           text=True, capture_output=True, check=True).stdout
    assert shown == notes
    shown = subprocess.run(['git', 'show', f'{branch}:{EXERCISES}/homework-p01/solution.json'], cwd=fork,
                           env=env, text=True, capture_output=True, check=True).stdout
    assert shown == payload
    assert git('log', '-1', '--format=%s', branch, cwd=fork, env=env) == f'Turn in session 01 homework ({HANDLE})'
    changed = git('diff', '--name-only', 'main', branch, cwd=fork, env=env).splitlines()
    assert changed and all(name.startswith(EXERCISES + '/') for name in changed), changed
