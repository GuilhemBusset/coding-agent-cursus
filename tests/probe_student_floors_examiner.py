"""Compare checked-in bootstrap floors with the newest setup check without importing it."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_all_four_bootstrap_floors_equal_the_latest_check():
    checks = sorted(ROOT.glob('sessions/*/exercises/check_setup.py'))
    nodes = ast.parse(checks[-1].read_text()).body
    expected = next(ast.literal_eval(n.value) for n in nodes if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'FLOORS' for t in n.targets))
    actual = {}
    for line in (ROOT / 'setup/student/versions.env').read_text().splitlines():
        key, _, value = line.partition('=')
        if key.endswith('_FLOOR'):
            actual[key[:-6].lower()] = tuple(map(int, value.split('.')))
    assert actual == expected
