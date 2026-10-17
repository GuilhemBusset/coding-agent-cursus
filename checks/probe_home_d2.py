"""Independent examiner probe for issue 45 D2."""

from html.parser import HTMLParser
from pathlib import Path
import json
import re
import shutil
import subprocess

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

def run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=50)

def cancelled_plan():
    import csv
    with (PACK / 'data/trips.csv').open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    return dict(status='feasible', objective=sum(float(r['cancel_penalty']) for r in rows),
                assign={}, cancel={r['trip_id']: 1 for r in rows}, charge={})

def test_d2_rubric_matches_the_real_checker_and_gate(tmp_path):
    p = page()
    for n in range(1, 5):
        assert 'What a good answer looks like' in p.sections[f'part-{n}']
    grading = ' '.join(p.sections['grading'].split()).lower()
    assert 'feasibility proven by the checker counts more than the objective value' in grading
    assert 'feasible incumbent' in p.sections['part-3']
    copy = tmp_path / 'session'
    shutil.copytree(PACK, copy / 'exercises/homework-p01')
    shutil.copyfile(SESSION / 'exercises/turn-in-check.sh', copy / 'exercises/turn-in-check.sh')
    (copy / 'exercises/homework-p01/solution.json').write_text(json.dumps(cancelled_plan()))
    checked = run(['uv', 'run', '--no-project', '--python', '3.12', 'python',
                   'exercises/homework-p01/p01_checker.py'], copy)
    assert checked.returncode == 1, checked.stdout + checked.stderr
    errors = re.findall(r'^([a-z-]+):', checked.stdout, flags=re.M)
    assert 'optimality' in errors, checked.stdout
    contracts = {'coverage', 'integrality', 'sequence', 'maintenance', 'charging-window',
                 'charging-power', 'charger-capacity', 'soc', 'objective', 'status', 'format', 'data'}
    assert not (set(errors) & contracts), checked.stdout
    gate = run(['bash', 'exercises/turn-in-check.sh'], copy)
    assert gate.returncode == 0 and 'optimality:' in gate.stdout, gate.stdout + gate.stderr

def test_d2_rubric_does_not_promise_an_unprinted_checker_status(tmp_path):
    p = page()
    solution = tmp_path / 'solution.json'
    solution.write_text(json.dumps(cancelled_plan()))
    checked = run(['uv', 'run', '--no-project', '--python', '3.12', 'python',
                   str(PACK / 'p01_checker.py'), str(solution)], SESSION)
    assert checked.returncode == 1, checked.stdout + checked.stderr
    # The checker uses the same summary formatter for passing and failing plans.
    # Any status the rubric attributes to that summary must actually be printed.
    rubric = ' '.join(p.sections['part-3'].split())
    if re.search(r'\bsummary shows status\b', rubric):
        assert re.search(r'\bstatus\s*[:=]\s*(optimal|feasible)\b', checked.stdout), (
            'The rubric says the checker summary shows status, but the real checker '
            'prints objectives and gap only. Identify solution.json as the source '
            'of status, or remove that output claim.\n' + checked.stdout)
