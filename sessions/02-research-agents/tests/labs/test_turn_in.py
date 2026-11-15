"""Truthful submission acceptance, independent grading and tamper/secret rejection."""

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from test_standalone import SESSION, command, offline


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


@pytest.fixture(scope='module')
def complete():
    assert command(['node', '--version'], SESSION).stdout.strip() == 'v24.15.0'
    if not (SESSION / 'node_modules/@earendil-works/pi-agent-core/package.json').exists():
        npm = shutil.which('npm')
        assert npm
        command([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'], SESSION)
    with TemporaryDirectory(prefix='s2-complete-submission-') as temporary:
        exercises = Path(temporary) / 'exercises'
        exercises.mkdir()
        for group in ('harness', 'prompts'):
            shutil.copytree(SESSION / 'exercises' / group, exercises / group)
        (exercises / 'home-notes.md').write_text('Synthetic outage exercise. Peer review pending. No live pass.\n', encoding='utf-8')
        submission = exercises / 'runs/submission'
        submission.mkdir(parents=True)
        (submission / 'peer-audit.md').write_text('Pending: no human peer available. All machine grades are provisional.\n', encoding='utf-8')
        examples = SESSION / 'exercises/fixed/examples'
        for kind in ('harness', 'prompt'):
            spec = read(examples / (kind + '.json'))
            for field in ('baseline', 'candidate', 'settings', 'rating_export'):
                spec[field] = str((examples / spec[field]).resolve())
            spec['scripts'] = {case: str((examples / path).resolve()) for case, path in spec['scripts'].items()}
            spec['mode'] = 'submission'
            path = Path(temporary) / (kind + '.json')
            write(path, spec)
            offline('evaluate', 'compare', '--experiment', path, '--output', submission / kind, codes=(0, 1))
        offline('turn_in_check', '--exercises', exercises, '--seal')
        yield exercises


def test_complete_low_quality_is_accepted_without_live_pass(complete):
    before = {p: p.read_bytes() for p in (complete / 'runs/submission').rglob('scorecard.json')}
    result = read_result(offline('turn_in_check', '--exercises', complete))
    assert result['accepted'] and not result['comparisons']['harness']['quality_pass']
    assert result['comparisons']['prompt']['quality_pass']
    assert result['live_verification'] == 'unverified' and result['live_pass'] is False
    assert all(p.read_bytes() == data for p, data in before.items())


def read_result(result):
    return json.loads(result.stdout)


@pytest.fixture
def workspace():
    with TemporaryDirectory(prefix='s2-submission-test-') as temporary:
        yield Path(temporary)


@pytest.mark.parametrize('damage', ['missing-trial', 'hash', 'malformed', 'schema', 'journal', 'score', 'controls', 'rating', 'schedule', 'secret', 'notes-secret', 'frozen'])
def test_rejects_invalid_submission(complete, workspace, damage):
    exercises = workspace / 'exercises'
    shutil.copytree(complete, exercises)
    root = exercises / 'runs/submission'
    attempt = root / 'harness/runs/candidate-01'
    if damage == 'missing-trial':
        shutil.rmtree(attempt)
    elif damage == 'hash':
        (root / 'peer-audit.md').write_text('changed after sealing', encoding='utf-8')
    elif damage == 'malformed':
        (attempt / 'claims.json').write_text('{broken', encoding='utf-8')
    elif damage == 'schema':
        write(attempt / 'claims.json', dict(claims='invalid'))
    elif damage == 'journal':
        (attempt / 'dispatches.jsonl').write_text('{broken', encoding='utf-8')
    elif damage == 'score':
        score = read(attempt / 'scorecard.json')
        score['quality_pass'] = True
        write(attempt / 'scorecard.json', score)
    elif damage in ('controls', 'schedule'):
        path = root / 'harness/shared.json'
        shared = read(path)
        if damage == 'controls':
            shared['settings']['connection']['model'] = 'other-model'
        else:
            shared['schedule'].pop()
        write(path, shared)
    elif damage == 'rating':
        (root / 'harness/cache/exercises/fixed/grading/engine.py').write_text('raise Exception()', encoding='utf-8')
    elif damage == 'frozen':
        (root / 'prompt/versions/candidate/harness/main.ts').write_text('// changed', encoding='utf-8')
    elif damage == 'notes-secret':
        (exercises / 'extra-notes.md').write_text('sk-' + 'testCredential1234567890' * 2, encoding='utf-8')
    else:
        (exercises / 'prompts/system.md').write_text('sk-' + 'testCredential1234567890' * 2, encoding='utf-8')
    # --seal proves these are behavioural checks, not just the outer file list.
    result = offline('turn_in_check', '--exercises', exercises, *([] if damage == 'hash' else ['--seal']), codes=(1,))
    assert not read_result(result)['accepted']
    assert 'testCredential' not in result.stdout


def test_bash_wrapper_uses_actual_validator(complete, workspace):
    session = workspace / 'session'
    session.mkdir()
    for file in ('pyproject.toml', 'uv.lock', 'README.md'):
        shutil.copyfile(SESSION / file, session / file)
    shutil.copytree(complete, session / 'exercises')
    shutil.copytree(SESSION / 'exercises/fixed', session / 'exercises/fixed', ignore=shutil.ignore_patterns('__pycache__'))
    gate = SESSION / 'exercises/turn-in-check.sh'
    bash = 'bash'
    if sys.platform == 'win32':
        # PATH's bash.exe can be the WSL launcher. Use the installed Git Bash
        # explicitly, keeping the validator's Python/uv runtime native Windows.
        git_exec = Path(command(['git', '--exec-path'], session).stdout.strip())
        candidates = [root / 'bin/bash.exe' for root in git_exec.parents]
        git_bash = next((path for path in candidates if path.is_file()), None)
        assert git_bash is not None, 'Git for Windows with Git Bash is required'
        bash = str(git_bash)
    command([bash, gate.as_posix()], session)
    (session / 'exercises/runs/submission/peer-audit.md').unlink()
    command([bash, gate.as_posix()], session, codes=(1,))
