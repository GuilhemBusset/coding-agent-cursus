"""Independent examiner probe for issue 45 A1."""

from html.parser import HTMLParser
from pathlib import Path
import importlib.util
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]

SESSION = ROOT / 'sessions/01-fundamentals'

SHEET = SESSION / 'exercises/home.html'

PACK = SESSION / 'exercises/homework-p01'

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections = {}; self.blocks = {}; self.links = []
        self.section = None; self.pre = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'section':
            self.section = attrs.get('id'); self.sections[self.section] = ''
        if tag == 'pre':
            self.pre = attrs.get('aria-label'); self.blocks[self.pre] = ''
        if 'href' in attrs: self.links.append(attrs['href'])
    def handle_data(self, text):
        if self.section: self.sections[self.section] += text
        if self.pre: self.blocks[self.pre] += text
    def handle_endtag(self, tag):
        if tag == 'section': self.section = None
        if tag == 'pre': self.pre = None

def page():
    result = Page(); result.feed(SHEET.read_text(encoding='utf-8')); return result

def cancelled_plan():
    import csv
    with (PACK / 'data/trips.csv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    return dict(status='feasible', objective=sum(float(r['cancel_penalty']) for r in rows),
                assign={}, cancel={r['trip_id']: 1 for r in rows}, charge={})

def test_a1_sheet_artifacts_reach_homework_branch_via_fork(tmp_path):
    # Reuse only the established offline environment, with real git/hooks/bare receivers.
    # gh describes a non-owner; GIT_ALLOW_PROTOCOL=file prevents live pushes.
    source = ROOT / 'tests/turn_in/test_turn_in_script.py'
    spec = importlib.util.spec_from_file_location('exam45_turnin', source)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    box = module.Sandbox(tmp_path, permission='READ', handle='sheet-student')
    sheet = page()
    notes = sheet.blocks['Template for exercises/home-notes.md'].replace('<your GitHub handle>', box.handle)
    box.edit('home-notes.md', notes)
    shutil.copytree(PACK, box.repo / box.exercises / 'homework-p01')
    shutil.copyfile(SESSION / 'exercises/turn-in-check.sh', box.repo / box.exercises / 'turn-in-check.sh')
    box.edit('homework-p01/solution.json', json.dumps(cancelled_plan()))
    result = box.run('01')
    assert 'Compare with the course:' in result.stdout, result.stdout
    assert 'homework/s01/sheet-student' in result.stdout, result.stdout
    fork = box.remotes[box.fork_name]
    for path in ('home-notes.md', 'homework-p01/solution.json', 'homework-p01/p01_model.py'):
        value = box.git('show', f'{box.branch}:{box.exercises}/{path}', cwd=fork)
        assert value.stdout.strip(), path
    assert json.loads(box.git('show', f'{box.branch}:{box.exercises}/homework-p01/solution.json', cwd=fork).stdout) == cancelled_plan()
    assert box.git('log', '-1', '--format=%s', box.branch, cwd=fork).stdout.strip() == 'Turn in session 01 homework (sheet-student)'
