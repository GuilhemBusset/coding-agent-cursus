"""Independent regression probes for behavior-sensitive lint fixes."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXERCISES = ROOT / "sessions/01-fundamentals/exercises"


def load(relative):
    path = EXERCISES / relative
    spec = importlib.util.spec_from_file_location("issue148_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_failed_subprocess_still_returns_status_and_keeps_output_private():
    setup = load("check_setup.py")
    code, output = setup.run([
        sys.executable, "-c",
        'import sys; print("public"); print("private", file=sys.stderr); sys.exit(7)',
    ])
    assert code == 7
    assert output.strip() == "public"


def test_background_recovery_reraises_the_original_failure():
    setup = load("check_setup.py")
    error = KeyboardInterrupt("probe interruption")

    def fail():
        raise error

    with pytest.raises(KeyboardInterrupt) as caught:
        setup.Background(fail).result()
    assert caught.value is error


def test_maintenance_is_checked_for_each_vehicle():
    checker = load("homework-p01/p01_checker.py")
    data = checker.load_data()
    vehicles = list(data["vehicles"])
    for index, vehicle in enumerate(data["vehicles"].values()):
        vehicle["maintenance"] = (index * 30, (index + 1) * 30)
    charge = {vid: [{"slot": checker.hhmm(index * 30), "charger": "slow", "kwh": 0}]
              for index, vid in enumerate(vehicles)}
    failures = []
    checker._schedule(data, {}, charge, lambda tag, message: failures.append((tag, message)))
    maintenance = [message for tag, message in failures if tag == "maintenance"]
    assert len(maintenance) == len(vehicles)
    for vid in vehicles:
        assert any(message.startswith(f"maintenance: {vid} charges") for message in maintenance)
