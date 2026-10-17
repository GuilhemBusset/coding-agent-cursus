"""Independent checks for issue 94: ingest failure-shaped commands and count their tests."""
import shlex
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/implementation-loop'))
from implement_loop import verify
from implement_loop.agents import BuildResult
from implement_loop.config import Caps
from implement_loop.engine import Engine
from implement_loop.model import CheckSpec, IssueState


def engine_and_state():
    events = []
    engine = Engine.__new__(Engine)
    engine.caps = Caps()
    engine.store = SimpleNamespace(event=lambda kind, **fields: events.append((kind, fields)))
    state = IssueState(number=24, plan={'items': [
        {'id': 'D2', 'proof': 'test'}, {'id': 'A1', 'proof': 'command'}]})
    return engine, state, events


def test_D1_failure_shaped_command_runs_and_accounts_for_unittest_probe():
    engine, state, events = engine_and_state()
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / 'probe.py'
        path.write_text('import unittest\nclass Probe(unittest.TestCase):\n'
                        '    def test_single_agent(self):\n        self.assertEqual(2 + 2, 4)\n')
        command = f'{shlex.quote(sys.executable)} -m pytest -q -p no:cacheprovider probe.py'
        engine._absorb_build(state, BuildResult(status='done', tests=['probe.py'], commands=[
            CheckSpec('D2/A1: examiner locked probe', command=command)]))
        assert len(state.commands) == 1, 'the probe selection command was discarded'
        assert state.commands[0]['criterion'] == 'D2'
        ok, evidence, problems, ran = verify.verify(root, engine._specs(state), 'examiner-head',
            root / 'reports', {}, ['probe.py'], None, check_tamper=False)
        assert ok, problems
        assert ran == ['probe.py::Probe::test_single_agent']
        assert not verify.unselected(root, ['probe.py'], {'*': ran}, {})
        assert not events


def test_D1_normalization_preserves_locked_command_approval():
    engine, state, events = engine_and_state()
    old = {'criterion': 'D2', 'command': 'old-command', 'cwd': '.', 'author': 'builder'}
    state.commands = [old.copy()]
    state.examined_sha = 'locked-head'
    engine._absorb_build(state, BuildResult(status='done', commands=[
        CheckSpec('D2, A1: examiner probes', command='new-command')]))
    assert state.commands == [old], 'normalization must not replace a locked command without approval'
    assert len(state.requests) == 1
    request = state.requests[0]
    assert (request['kind'], request['item'], request['status']) == ('command_change', 'D2', 'pending')
    assert request['commands'][0]['command'] == 'new-command'


def test_D1_unknown_criterion_is_observable():
    engine, state, events = engine_and_state()
    engine._absorb_build(state, BuildResult(status='done', commands=[
        CheckSpec('Regression: the whole suite', command='run-the-suite')]))
    assert not state.commands
    assert state.dropped and 'Regression: the whole suite' in state.dropped[0]
    assert events[0][0] == 'commands_dropped'
    assert 'run-the-suite' in events[0][1]['commands'][0]
