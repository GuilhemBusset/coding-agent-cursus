"""The environment probes, the healing order, and the user-space library recipe, with a fake
host: no network, no browser, no apt."""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from helpers import REPO_ROOT

from implement_loop import environment
from implement_loop.environment import Probe

READY = "Ready: Chromium launched and rendered local file:// HTML with networking disabled."
NO_LIBS = "Not ready: error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory"


def done(cmd, code=0, out="", err=""):
    return subprocess.CompletedProcess(cmd, code, out, err)


LOCKED = {"playwright": "1.63.0", "@axe-core/playwright": "4.13.0"}
LOCKFILE = {"lockfileVersion": 3, "packages": {
    "": {"devDependencies": LOCKED},
    **{f"node_modules/{name}": {"version": version, "dev": True} for name, version in LOCKED.items()},
    "node_modules/fsevents": {"version": "2.3.2", "optional": True},  # platform-specific: not required
}}


def install_packages(setup_dir: Path, mode: str = "locked") -> None:
    """node_modules beside a lockfile: "locked", "partial" (no playwright), "stale" (an older axe)."""
    for name, version in LOCKED.items():
        if mode == "partial" and name == "playwright":
            continue
        if mode == "stale" and name == "@axe-core/playwright":
            version = "4.12.0"
        pkg = setup_dir / "node_modules" / name
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "package.json").write_text(json.dumps({"name": name, "version": version}))


class FakeHost:
    """Plays node, npm, Playwright's CLI, the doctor, uv, ldd and the library recipe. The doctor's
    answer follows the host's state, which the repairs change: `npm ci` fills the directory it runs
    in, Playwright's CLI installs the browser, and the recipe activates copies the doctor sees only
    through CURSUS_BROWSER_LIBS. `modules` is the installed node_modules ("locked", "partial",
    "stale" or "missing"); `npm` is what `npm ci` leaves ("locked", "partial", "broken", "fails")."""

    def __init__(self, root: Path, state_dir: Path, *, node="v22.11.0", modules="locked", browser=True,
                 libs=True, uv=True, pytest="pytest 8.3.5", npm="locked", recipe_works=True,
                 copy_launches=True, bad_copies=(), doctor_error=None):
        self.root, self.state_dir = root, state_dir
        self.node, self.browser, self.libs, self.uv, self.pytest = node, browser, libs, uv, pytest
        self.npm, self.recipe_works, self.copy_launches = npm, recipe_works, copy_launches
        self.bad_copies, self.doctor_error = set(bad_copies), doctor_error
        self.copies = 0
        setup = root / "setup"
        setup.mkdir(parents=True, exist_ok=True)
        (setup / "package.json").write_text(json.dumps({"devDependencies": LOCKED}))
        (setup / "package-lock.json").write_text(json.dumps(LOCKFILE))
        if modules != "missing":
            install_packages(setup, modules)
            (setup / "node_modules" / ".original").write_text("")  # marks the installation heal found
        self.exe = root / "chrome"
        self.exe.write_text("")
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[:2] == ["node", "--version"]:
            if self.node is None:
                raise FileNotFoundError(cmd[0])
            return done(cmd, out=self.node + "\n")
        if cmd[:2] == ["node", "setup/doctor.mjs"]:
            return self.doctor(kw.get("env") or {})
        if cmd[:2] == ["npm", "ci"]:
            if self.npm == "fails":
                return done(cmd, 1, "", "npm error code ETIMEDOUT\nnpm error network request failed")
            install_packages(Path(kw["cwd"]), "partial" if self.npm == "partial" else "locked")
            if self.npm == "broken":
                (Path(kw["cwd"]) / "node_modules" / ".broken").write_text("")
            return done(cmd, out="added 4 packages\n")
        if cmd[0] == "node" and cmd[1].endswith("cli.js"):
            self.browser = True
            return done(cmd, out="Chromium downloaded to /cache\n")
        if len(cmd) > 1 and cmd[1].endswith("browser-libs.py"):
            return self.recipe(cmd)
        if cmd[0] == "uv":
            if not self.uv:
                raise FileNotFoundError("uv")
            return done(cmd, out=self.pytest + "\n")
        if cmd[0] == "ldd":
            return done(cmd, out="\tlibnspr4.so => not found\n\tlibc.so.6 => /lib/libc.so.6 (0x1)\n")
        raise AssertionError(f"unexpected command {cmd}")

    def recipe(self, cmd):
        dest = Path(cmd[cmd.index("--dest") + 1])
        if "--rollback" in cmd:  # the pointer moves the real recipe makes (RecipeTests covers it)
            previous = (dest / "previous").read_text().strip()
            if previous.startswith("libs-"):
                (dest / "current").write_text(previous + "\n")
            else:
                (dest / "current").unlink()
            (dest / "previous").unlink()
            return done(cmd, out="browser-libs: rolled back\n")
        if not self.recipe_works:
            return done(cmd, 1, "browser-libs: failed: chrome still misses libfoo.so.1\nbrowser-libs: no copy is active\n")
        self.copies += 1
        name = f"libs-{self.copies}"
        (dest / name).mkdir(parents=True)
        (dest / name / "manifest.json").write_text(json.dumps({"lib_dirs": ["root/usr/lib"]}))
        current = (dest / "current").read_text().strip() if (dest / "current").exists() else "none"
        (dest / "previous").write_text(current + "\n")
        (dest / "current").write_text(name + "\n")
        if not self.copy_launches:
            self.bad_copies.add(name)
        return done(cmd, out=f"browser-libs: active copy: {dest / name}\n")

    def doctor(self, env):
        head = f"playwright: 1.63.0\nNode: {self.node}\nChromium executable: {self.exe}\n"
        if self.doctor_error:
            return done([], 1, head, self.doctor_error)
        if not self.browser:
            return done([], 1, head, "Not ready: browserType.launch: Executable doesn't exist at /cache/chrome-headless-shell\n")
        libs = env.get("CURSUS_BROWSER_LIBS")
        copy_works = libs and Path(libs, "manifest.json").is_file() and Path(libs).name not in self.bad_copies
        if not self.libs and not copy_works:
            return done([], 1, head, NO_LIBS + "\n")
        return done([], 0, head + READY + "\n")

    def commands(self) -> list[list[str]]:
        return [cmd for cmd, _ in self.calls]

    def repairs(self) -> list[str]:
        out = []
        for c in self.commands():
            if c[:2] == ["npm", "ci"]:
                out.append("npm ci")
            elif any("html-pages" in arg for arg in c):
                out.append("html-pages")
            elif len(c) > 1 and c[1].endswith("cli.js"):
                out.append("playwright install")
            elif len(c) > 1 and c[1].endswith("browser-libs.py"):
                out.append("browser-libs --rollback" if "--rollback" in c else "browser-libs")
        return out


class EnvironmentTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="loop-env-"))
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.state = self.tmp / "state"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def host(self, **kw) -> FakeHost:
        return FakeHost(self.root, self.state, **kw)

    def activate(self, name="libs-0123", manifest=True) -> Path:
        dest = self.state / environment.LIBS_DIR
        (dest / name).mkdir(parents=True)
        if manifest:
            (dest / name / "manifest.json").write_text(json.dumps({"lib_dirs": ["root/usr/lib"]}))
        (dest / "current").write_text(name + "\n")
        return dest / name

    def modules(self) -> set[str]:
        return {p.name for p in (self.root / "setup" / "node_modules").iterdir()}


class ProbeTests(EnvironmentTestCase):
    def test_a_healthy_host_passes_each_kind(self):
        probes = environment.probe(self.root, self.state, self.host())
        self.assertEqual([(p.name, p.kind, p.ok) for p in probes],
                         [("node", "node", True), ("chromium", "browser", True), ("pytest", "python-tests", True)])
        self.assertEqual(probes[0].detail, "Node v22.11.0; the locked npm packages are installed")
        self.assertEqual(probes[1].detail, READY)
        self.assertEqual(probes[2].detail, "pytest 8.3.5 via uv run --no-project")

    def test_the_pinned_runner_is_the_one_ci_uses(self):
        host = self.host()
        environment.probe(self.root, self.state, host)
        uv = next(c for c in host.commands() if c[0] == "uv")
        self.assertEqual(uv, ["uv", "run", "--no-project", "--with", "pytest==8.3.5", "python", "-m", "pytest", "--version"])
        workflow = (REPO_ROOT / ".github" / "workflows" / "checks.yml").read_text()
        self.assertIn(environment.PYTEST_PIN, workflow)

    def test_failures_are_parsed_per_probe(self):
        probes = environment.probe(self.root, self.state, self.host(node="v20.18.0", uv=False))
        self.assertEqual([p.ok for p in probes], [False, False, False])
        self.assertIn("older than 22", probes[0].detail)
        self.assertIn("not checked", probes[1].detail)
        self.assertEqual(probes[2].detail, "uv not found on PATH")
        node, _, pytest = environment.probe(self.root, self.state, self.host(node=None, pytest="pytest 9.0.0"))
        self.assertEqual(node.detail, "node not found on PATH")
        self.assertFalse(pytest.ok)

    def test_missing_node_modules_fails_the_node_probe(self):
        node, browser, _ = environment.probe(self.root, self.state, self.host(modules="missing"))
        self.assertFalse(node.ok)
        self.assertIn("setup/node_modules missing", node.detail)
        self.assertFalse(browser.ok)

    def test_packages_missing_or_not_as_locked_fail_the_node_probe(self):
        node, _, _ = environment.probe(self.root, self.state, self.host(modules="partial"))
        self.assertFalse(node.ok)
        self.assertIn("npm packages not as locked: playwright missing", node.detail)
        self.assertNotIn("fsevents", node.detail, "optional packages are not required")
        shutil.rmtree(self.root / "setup")
        node, _, _ = environment.probe(self.root, self.state, self.host(modules="stale"))
        self.assertIn("@axe-core/playwright 4.12.0 (locked 4.13.0)", node.detail)

    def test_the_doctor_reports_the_shared_library_error(self):
        _, browser, _ = environment.probe(self.root, self.state, self.host(libs=False))
        self.assertEqual(browser.detail, NO_LIBS)
        self.assertEqual(environment._failure(browser.detail), "libraries")

    def test_the_doctor_sees_the_active_copy_through_its_environment(self):
        copy = self.activate()
        host = self.host(libs=False)
        _, browser, _ = environment.probe(self.root, self.state, host)
        self.assertTrue(browser.ok)
        env = next(kw["env"] for cmd, kw in host.calls if cmd[:2] == ["node", "setup/doctor.mjs"])
        self.assertEqual(env["CURSUS_BROWSER_LIBS"], str(copy))
        self.assertEqual(env.get("LD_LIBRARY_PATH"), os.environ.get("LD_LIBRARY_PATH"), "only browser.mjs sets it")

    @unittest.skipUnless(sys.platform.startswith("linux"), "ldd is Linux-only")
    def test_ldd_names_missing_libraries_the_doctor_message_hides(self):
        # Playwright's host check puts its message in a box after the first line, which the
        # doctor does not print; ldd on the printed executable recovers the cause.
        host = self.host(doctor_error="Not ready: browserType.launch: \n")
        _, browser, _ = environment.probe(self.root, self.state, host)
        self.assertIn("missing shared libraries libnspr4.so", browser.detail)
        self.assertEqual(environment._failure(browser.detail), "libraries")
        self.assertIn(["ldd", str(host.exe)], host.commands())

    def test_a_missing_browser_binary_is_recognised(self):
        _, browser, _ = environment.probe(self.root, self.state, self.host(browser=False))
        self.assertEqual(environment._failure(browser.detail), "browser")


class HealTests(EnvironmentTestCase):
    def assert_no_privilege(self, host):
        for cmd in host.commands():
            self.assertNotIn("sudo", cmd)
            self.assertNotIn("--with-system-deps", cmd)
            self.assertNotIn("--with-deps", cmd)
        self.assertNotIn("html-pages", host.repairs(), "the human setup path replaces node_modules in place")

    def assert_npm_state_clean(self):
        npm = self.state / environment.NPM_DIR
        self.assertEqual(list(npm.iterdir()) if npm.exists() else [], [], "no staging directory or backup is left")

    def test_a_healthy_host_needs_nothing(self):
        host = self.host()
        self.assertEqual(environment.heal(self.root, self.state, host), [])
        self.assertEqual(host.repairs(), [])

    def test_everything_missing_is_repaired_in_stages_in_order(self):
        host = self.host(modules="missing", browser=False, libs=False)
        actions = environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), ["npm ci", "playwright install", "browser-libs"])
        npm_cmd, npm_kw = next((c, kw) for c, kw in host.calls if c[:2] == ["npm", "ci"])
        self.assertEqual(npm_cmd, ["npm", "ci", "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund"])
        self.assertEqual(Path(npm_kw["cwd"]).parent, self.state / environment.NPM_DIR)
        self.assertEqual(len(actions), 3)
        self.assertIn("staging directory", actions[0])
        self.assertIn("install --no-remove chromium", actions[1])
        self.assertIn("unpacked Chromium's shared libraries", actions[2])
        recipe = next(c for c in host.commands() if c[1].endswith("browser-libs.py"))
        self.assertEqual(recipe, [sys.executable, str(self.root / "setup" / "browser-libs.py"),
                                  "--dest", str(self.state / "browser-libs")])
        self.assertTrue(all(p.ok for p in environment.probe(self.root, self.state, host)))
        self.assert_npm_state_clean()
        self.assert_no_privilege(host)

    def test_an_incomplete_or_stale_install_is_replaced_by_a_staged_one(self):
        for mode in ("partial", "stale"):
            with self.subTest(mode=mode):
                shutil.rmtree(self.root / "setup", ignore_errors=True)
                host = self.host(modules=mode)
                actions = environment.heal(self.root, self.state, host)
                self.assertEqual(host.repairs(), ["npm ci"])
                self.assertIn("swapped them in", actions[0])
                self.assertNotIn(".original", self.modules(), "the staged install replaced it")
                self.assertTrue(environment.probe(self.root, self.state, host)[0].ok)
                self.assert_npm_state_clean()

    def test_a_failed_or_incomplete_staged_install_leaves_node_modules_alone(self):
        for npm, words in (("fails", "npm ci failed"), ("partial", "incomplete")):
            with self.subTest(npm=npm):
                shutil.rmtree(self.root / "setup", ignore_errors=True)
                host = self.host(modules="stale", npm=npm)
                actions = environment.heal(self.root, self.state, host)
                self.assertEqual(host.repairs(), ["npm ci"])
                self.assertIn(words, actions[0])
                self.assertIn("unchanged", actions[0])
                self.assertIn(".original", self.modules())
                self.assert_npm_state_clean()

    def test_a_swapped_install_that_fails_the_reprobe_is_put_back(self):
        real = environment._package_problems

        def problems(setup_dir):  # the swapped-in install turns out broken where it lands
            broken = (setup_dir / "node_modules" / ".broken").exists() and setup_dir == self.root / "setup"
            return ["playwright unreadable"] if broken else real(setup_dir)
        host = self.host(modules="stale", npm="broken")
        with mock.patch.object(environment, "_package_problems", problems):
            actions = environment.heal(self.root, self.state, host)
        self.assertIn("restored the previous setup/node_modules", actions[0])
        self.assertIn(".original", self.modules())
        self.assertNotIn(".broken", self.modules())
        self.assert_npm_state_clean()

    def test_a_missing_browser_alone_runs_only_playwrights_installer(self):
        host = self.host(browser=False)
        actions = environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), ["playwright install"])
        cmd, kw = next((c, kw) for c, kw in host.calls if c[0] == "node" and c[1].endswith("cli.js"))
        self.assertEqual(cmd, ["node", str(self.root / "setup" / "node_modules" / "playwright" / "cli.js"),
                               "install", "--no-remove", "chromium"])
        self.assertEqual(kw["cwd"], self.root / "setup")
        self.assertIn(".original", self.modules(), "node_modules is left alone")
        self.assertIn("installed the Chromium binary", actions[0])
        self.assert_no_privilege(host)

    def test_shared_library_errors_go_straight_to_the_library_recipe(self):
        host = self.host(libs=False)
        environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), ["browser-libs"])
        self.assertEqual(environment.browser_env(self.state),
                         {"CURSUS_BROWSER_LIBS": str(self.state / "browser-libs" / "libs-1")})
        self.assert_no_privilege(host)

    def test_a_new_copy_chromium_still_fails_with_is_rolled_back(self):
        old = self.activate("libs-0123")
        host = self.host(libs=False, copy_launches=False, bad_copies={"libs-0123"})
        actions = environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), ["browser-libs", "browser-libs --rollback"])
        self.assertIn("Chromium still fails with it", actions[0])
        self.assertIn("rolled back to libs-0123", actions[0])
        self.assertEqual(environment.browser_env(self.state), {"CURSUS_BROWSER_LIBS": str(old)})

    def test_a_first_copy_that_does_not_help_is_deactivated(self):
        host = self.host(libs=False, copy_launches=False)
        actions = environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), ["browser-libs", "browser-libs --rollback"])
        self.assertIn("deactivated it (no copy was active before)", actions[0])
        self.assertEqual(environment.browser_env(self.state), {})

    def test_other_browser_failures_run_no_recipe(self):
        host = self.host(doctor_error="Not ready: page.goto: Timeout 30000ms exceeded.\n")

        def nothing_missing(cmd, **kw):  # ldd finds every library: not a library problem
            return done(cmd, out="\tlibc.so.6 => /lib/libc.so.6 (0x1)\n") if cmd[0] == "ldd" else host(cmd, **kw)
        self.assertEqual(environment.heal(self.root, self.state, nothing_missing), [])
        self.assertEqual(host.repairs(), [])

    def test_a_failing_recipe_runs_once_and_says_so(self):
        host = self.host(libs=False, recipe_works=False)
        actions = environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), ["browser-libs"])
        self.assertIn("could not unpack", actions[0])
        self.assertIn("libfoo.so.1", actions[0])
        self.assertEqual(environment.browser_env(self.state), {})

    def test_without_node_nothing_is_attempted(self):
        host = self.host(node=None, modules="missing")
        actions = environment.heal(self.root, self.state, host)
        self.assertEqual(host.repairs(), [])
        self.assertIn("no recipe installs Node.js", actions[0])

    def test_a_missing_uv_is_reported(self):
        actions = environment.heal(self.root, self.state, self.host(uv=False))
        self.assertEqual(actions, ["no recipe installs uv; Python test checks stay unavailable"])


class BrowserEnvTests(EnvironmentTestCase):
    def test_no_copy_means_no_variable(self):
        self.assertEqual(environment.browser_env(self.state), {})

    def test_the_active_copy_is_named(self):
        copy = self.activate()
        self.assertEqual(environment.browser_env(self.state), {"CURSUS_BROWSER_LIBS": str(copy)})

    def test_a_pointer_without_a_finished_copy_is_ignored(self):
        self.activate(manifest=False)
        self.assertEqual(environment.browser_env(self.state), {})
        (self.state / "browser-libs" / "current").write_text("../elsewhere\n")
        self.assertEqual(environment.browser_env(self.state), {})


class FingerprintTests(unittest.TestCase):
    def test_it_depends_only_on_which_probes_pass(self):
        a = [Probe("node", True, "Node v22", "node"), Probe("chromium", False, "x", "browser")]
        b = [Probe("chromium", False, "other detail", "browser"), Probe("node", True, "Node v24", "node")]
        self.assertEqual(environment.fingerprint(a), environment.fingerprint(b))
        self.assertEqual(len(environment.fingerprint(a)), 12)
        healed = [Probe("node", True, "", "node"), Probe("chromium", True, "", "browser")]
        self.assertNotEqual(environment.fingerprint(a), environment.fingerprint(healed))


def load_recipe():
    spec = importlib.util.spec_from_file_location("browser_libs", REPO_ROOT / "setup" / "browser-libs.py")
    module = importlib.util.module_from_spec(spec)
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # no __pycache__ in setup/
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = saved
    return module


class FakeApt:
    """apt-get (simulate, download), dpkg -x, ldd and the doctor for the recipe. Each package
    unpacks one library; ldd finds a library only on the LD_LIBRARY_PATH it is given."""

    def __init__(self, needed=("libnspr4.so",), extra=(), version="1", launches=True):
        self.needed, self.extra, self.version, self.launches = list(needed), list(extra), version, launches
        self.calls: list[list[str]] = []
        self.launched: list[str] = []  # the CURSUS_BROWSER_LIBS each doctor run was given

    def __call__(self, cmd, cwd=None, env=None, **kw):
        self.calls.append(cmd)
        if cmd[0] == "node" and cmd[1].endswith("doctor.mjs"):
            libs = (env or {}).get("CURSUS_BROWSER_LIBS", "")
            self.launched.append(libs)
            if self.launches and Path(libs, "manifest.json").is_file():
                return done(cmd, out=READY + "\n")
            return done(cmd, 1, "Chromium executable: /x/chrome\n", "Not ready: browserType.launch: Target page, context or browser has been closed\n")
        if cmd[:3] == ["apt-get", "-s", "--no-install-recommends"]:
            return done(cmd, out="".join(f"Inst {p} (1.0 Ubuntu:26.04/resolute [amd64])\n" for p in self.extra))
        if cmd[:3] == ["apt-get", "download", "--print-uris"]:
            return done(cmd, out="".join(f"'http://archive/{p}.deb' {p}_1_amd64.deb 1 SHA512:00\n" for p in cmd[3:]))
        if cmd[:2] == ["apt-get", "download"]:
            for pkg in cmd[2:]:
                Path(cwd, f"{pkg}_{self.version}_amd64.deb").write_text(f"{pkg} {self.version}")
            return done(cmd)
        if cmd[:2] == ["dpkg", "-x"]:
            pkg = Path(cmd[2]).name.split("_")[0]
            lib = Path(cmd[3]) / "usr" / "lib" / "x86_64-linux-gnu"
            lib.mkdir(parents=True, exist_ok=True)
            (lib / f"{pkg}.so.1").write_text("")
            if pkg == "libnspr4":
                (lib / "libnspr4.so").write_text("")
            return done(cmd)
        if cmd[0] == "ldd":
            dirs = [Path(d) for d in (env or {}).get("LD_LIBRARY_PATH", "").split(":") if d]
            lines = []
            for name in self.needed:
                where = next((d / name for d in dirs if (d / name).exists()), None)
                lines.append(f"\t{name} => {where} (0x1)" if where else f"\t{name} => not found")
            return done(cmd, out="\n".join(lines) + "\n")
        raise AssertionError(f"unexpected command {cmd}")


@unittest.skipUnless(sys.platform.startswith("linux"), "the recipe is Linux-only")
class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = load_recipe()
        self.tmp = Path(tempfile.mkdtemp(prefix="loop-libs-"))
        self.dest = self.tmp / "libs"
        self.chrome = self.tmp / "chrome"
        self.chrome.write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_recipe(self, apt, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = self.recipe.main(["--dest", str(self.dest), "--packages", "libnspr4,libnss3",
                                     "--browser", str(self.chrome), *args], run=apt)
        return code, out.getvalue()

    def current(self):
        return (self.dest / "current").read_text().strip()

    def test_the_pinned_list_is_playwrights_chromium_list(self):
        bundle = REPO_ROOT / "setup" / "node_modules" / "playwright-core" / "lib" / "coreBundle.js"
        if not bundle.exists():
            self.skipTest("setup/node_modules is not installed")
        text = bundle.read_text()
        for platform in ("ubuntu24.04-x64", "ubuntu26.04-x64"):
            block = text[text.index(f'"{platform}": {{'):]
            chromium = block[block.index("chromium: ["):]
            names = [line.strip().strip('",') for line in chromium[len("chromium: ["):chromium.index("]")].splitlines()]
            self.assertEqual(sorted(n for n in names if n), sorted(self.recipe.PACKAGES), platform)

    def test_a_smoke_tested_copy_is_activated_and_the_previous_kept(self):
        code, out = self.run_recipe(FakeApt(version="1"))
        self.assertEqual(code, 0, out)
        first = self.current()
        manifest = json.loads((self.dest / first / "manifest.json").read_text())
        self.assertEqual(manifest["lib_dirs"], ["root/usr/lib/x86_64-linux-gnu"])
        self.assertEqual([p["name"] for p in manifest["packages"]], ["libnspr4", "libnss3"])
        self.assertFalse((self.dest / first / "debs").exists())
        self.assertIn("1 resolve from the unpacked copy", out)
        self.assertEqual((self.dest / "previous").read_text().strip(), "none")

        code, _ = self.run_recipe(FakeApt(version="2"))
        self.assertEqual(code, 0)
        second = self.current()
        self.assertNotEqual(first, second)
        self.assertEqual((self.dest / "previous").read_text().strip(), first)
        self.assertTrue((self.dest / first).is_dir())

        self.run_recipe(FakeApt(version="3"))
        self.assertEqual((self.dest / "previous").read_text().strip(), second)
        self.assertFalse((self.dest / first).exists(), "only the current and previous copies are kept")

    def test_a_failed_smoke_test_leaves_the_active_copy(self):
        self.run_recipe(FakeApt(version="1"))
        active = self.current()
        code, out = self.run_recipe(FakeApt(version="2", needed=("libnspr4.so", "libmissing.so.9")))
        self.assertEqual(code, 1)
        self.assertIn("still misses libmissing.so.9", out)
        self.assertIn(f"the active copy is unchanged: {self.dest / active}", out)
        self.assertEqual(self.current(), active)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir() if p.is_dir()), [active])

    def test_chromium_must_start_with_the_staged_copy_before_it_is_activated(self):
        apt = FakeApt(version="1")
        self.run_recipe(apt)
        self.assertEqual(len(apt.launched), 1)
        self.assertTrue(Path(apt.launched[0]).name.startswith("staging-"), "launched before activation")
        active = self.current()
        code, out = self.run_recipe(FakeApt(version="2", launches=False))
        self.assertEqual(code, 1)
        self.assertIn("Chromium does not start with the staged copy", out)
        self.assertEqual(self.current(), active)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir() if p.is_dir()), [active])

    def test_rollback_undoes_the_last_activation_once(self):
        self.run_recipe(FakeApt(version="1"))
        first = self.current()
        self.run_recipe(FakeApt(version="2"))
        second = self.current()
        code, out = self.run_recipe(FakeApt(), "--rollback")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.current(), first)
        self.assertFalse((self.dest / second).exists())
        self.assertFalse((self.dest / "previous").exists())
        code, out = self.run_recipe(FakeApt(), "--rollback")
        self.assertEqual(code, 1)
        self.assertIn("nothing to roll back", out)
        self.assertEqual(self.current(), first)

    def test_rolling_back_a_first_activation_leaves_no_copy(self):
        self.run_recipe(FakeApt(version="1"))
        first = self.current()
        code, out = self.run_recipe(FakeApt(), "--rollback")
        self.assertEqual(code, 0, out)
        self.assertIn("no copy is active", out)
        self.assertFalse((self.dest / "current").exists())
        self.assertFalse((self.dest / first).exists())

    def test_dependencies_apt_would_add_are_fetched_but_never_the_c_runtime(self):
        apt = FakeApt(extra=["libplc4", "libc6"])
        self.assertEqual(self.run_recipe(apt)[0], 0)
        download = next(c for c in apt.calls if c[:2] == ["apt-get", "download"])
        self.assertEqual(download[2:], ["libnspr4", "libnss3", "libplc4"])
        self.assertTrue(all("sudo" not in c for c in apt.calls))

    def test_a_dry_run_writes_nothing(self):
        apt = FakeApt()
        code, out = self.run_recipe(apt, "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.dest.exists())
        self.assertIn(["apt-get", "download", "--print-uris", "libnspr4", "libnss3"], apt.calls)
        self.assertFalse(any(c[:2] in (["apt-get", "download"], ["dpkg", "-x"]) and "--print-uris" not in c
                             for c in apt.calls))


if __name__ == "__main__":
    unittest.main()
