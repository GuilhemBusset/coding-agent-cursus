"""Independent version check for resuming the faulted run."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/implementation-loop'))
from implement_loop import VERSION


def test_D2_version_advances_past_faulted_release():
    assert tuple(map(int, VERSION.split('.'))) > (1, 0, 1)
