"""Independent issue 24 probes. Only temporary repositories receive pushes."""
import contextlib
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'sessions/01-fundamentals/exercises'
GIT = shutil.which('git')
BASH = shutil.which('bash')
PWSH = shutil.which('pwsh') or str(Path.home() / '.local/bin/pwsh')
UV = shutil.which('uv')
SECRET = 'PRIVATE_EXAMINER_TOKEN_83ac'
STUB = '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
if name == 'uv' and '--version' not in args:
    if os.environ.get('BOOT_FAIL'): sys.exit(int(os.environ['BOOT_FAIL']))
    os.execv(sys.executable, [sys.executable, args[-1]])
if '--version' in args:
    print({'gh':'gh version 2.60.0','uv':'uv 0.11.28','mise':'mise 2026.1.0',
           'claude':'claude 2.1.0','codex':'codex-cli 0.160.0'}[name]); sys.exit(0)
if name == 'gh':
    print('PRIVATE_EXAMINER_TOKEN_83ac', file=sys.stderr)
    if args[:2] == ['auth','status']: sys.exit(int(os.environ.get('AUTH_FAIL','0')))
    if args[:2] == ['api','user']: print('learner')
    elif args[:2] == ['repo','view']:
        print(json.dumps({'nameWithOwner':'instructor/course','parent':None,
                          'viewerPermission':os.environ.get('PERMISSION','WRITE')}))
    elif args[:2] == ['api','--paginate']: print('learner/course')
    sys.exit(0)
assert 'Reply with exactly: OK' in args, args
print('PRIVATE_EXAMINER_TOKEN_83ac', file=sys.stderr)
reply = os.environ.get('REPLY', 'OK')
if name == 'codex': pathlib.Path(args[args.index('--output-last-message')+1]).write_text(reply)
else: print(reply)
'''


class Quiet(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(403)
        self.end_headers()

    def log_message(self, *args):
        pass


class Probe(unittest.TestCase):
    @contextlib.contextmanager
    def machine(self, agent, **settings):
        real_uv = settings.pop('REAL_UV', False)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, binary = base / 'repo', base / 'bin'
            repo.mkdir(); binary.mkdir()
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('GIT_', 'CHECK_SETUP_', 'GH_', 'ANTHROPIC_', 'OPENAI_'))}
            env.update(HOME=str(base), PATH=str(binary), GIT_CONFIG_NOSYSTEM='1',
                       GIT_CONFIG_GLOBAL=os.devnull, ANTHROPIC_API_KEY=SECRET, OPENAI_API_KEY=SECRET)
            env.update(settings)
            if real_uv:
                env.update(UV_PYTHON_INSTALL_DIR=subprocess.check_output(
                    [UV, 'python', 'dir'], text=True).strip(), UV_OFFLINE='1')
            def git(*args, input=None):
                return subprocess.check_output([GIT, *args], cwd=repo, env=env,
                                               input=input, text=True, stderr=subprocess.DEVNULL).strip()
            git('init', '-q')
            git('config', 'user.name', 'Student')
            git('config', 'user.email', 'student@example.invalid')
            git('remote', 'add', 'origin', 'https://github.com/instructor/course.git')
            for slug in ('instructor/course', 'learner/course'):
                remote = base / (slug.replace('/', '-') + '.git')
                git('init', '--bare', '-q', str(remote))
                git('config', 'url.' + str(remote) + '.insteadOf', 'https://github.com/' + slug + '.git')
            shutil.copytree(SOURCE, repo / 'exercises')
            for name in ('git', 'dirname', 'date', 'uname'):
                (binary / name).symlink_to(shutil.which(name))
            for name in ('uv', 'gh', 'mise', agent):
                script = binary / name
                if name == 'uv' and real_uv:
                    script.symlink_to(UV)
                    continue
                script.write_text('#!' + sys.executable + '\n' + STUB)
                script.chmod(0o755)
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            env['CHECK_SETUP_URLS'] = 'http://127.0.0.1:' + str(server.server_port)
            def execute(shell):
                wrapper = repo / 'exercises' / ('check-setup.sh' if shell == 'bash' else 'check-setup.ps1')
                argv = [BASH, str(wrapper)] if shell == 'bash' else [PWSH, '-NoProfile', '-File', str(wrapper)]
                return subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, timeout=30)
            try:
                yield execute, git, base
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def summary(self, result, succeeds):
        self.assertEqual(result.returncode, 0 if succeeds else 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('----- BEGIN SETUP SUMMARY -----'), 1, result.stdout)
        self.assertEqual(result.stdout.count('----- END SETUP SUMMARY -----'), 1, result.stdout)
        self.assertIn('result: ' + ('PASS' if succeeds else 'FAIL'), result.stdout)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_D2_A1_single_agents(self):
        for agent in ('claude', 'codex'):
            with self.machine(agent) as (execute, git, base):
                for shell in ('bash', 'powershell'):
                    with self.subTest(agent=agent, shell=shell):
                        result = execute(shell)
                        self.summary(result, True)
                        for tool in ('git', 'gh', 'uv', 'mise', agent):
                            self.assertRegex(result.stdout, tool + r': PASS \d+\.\d+')
                        self.assertIn(agent + '-smoke: PASS', result.stdout)
                        self.assertIn(('codex' if agent == 'claude' else 'claude') + ': not installed (fine)', result.stdout)
                        self.assertIn('gh-auth: PASS', result.stdout)
                        self.assertIn('reachable (HTTP 403)', result.stdout)

    def test_D3_real_push_and_fork(self):
        for permission, slug in (('WRITE', 'instructor-course'), ('READ', 'learner-course')):
            with self.machine('codex', PERMISSION=permission) as (execute, git, base):
                remote = base / (slug + '.git')
                hook = remote / 'hooks' / 'pre-receive'
                log = base / 'push-log'
                hook.write_text('#!' + sys.executable + '\nimport sys\nfrom pathlib import Path\n'
                                + 'with Path(' + repr(str(log)) + ').open("a") as f: f.write(sys.stdin.read())\n')
                hook.chmod(0o755)
                for shell in ('bash', 'powershell'):
                    with self.subTest(permission=permission, shell=shell):
                        self.summary(execute(shell), True)
                        self.assertEqual(git('ls-remote', str(remote)), '')
                updates = [line.split() for line in log.read_text().splitlines()]
                self.assertEqual(len(updates), 4)
                self.assertTrue(all(row[2] == 'refs/heads/setup-check/learner' for row in updates))
                self.assertTrue(all(set(updates[i][0]) == {'0'} and set(updates[i+1][1]) == {'0'} for i in (0, 2)))

    def test_A2_failed_auth_and_smoke_hide_secrets(self):
        for settings in ({'AUTH_FAIL':'1'}, {'REPLY':SECRET}):
            with self.machine('claude', **settings) as (execute, git, base):
                for shell in ('bash', 'powershell'):
                    with self.subTest(settings=settings, shell=shell):
                        result = execute(shell)
                        self.summary(result, False)
                        self.assertIn(': FAIL', result.stdout)

    def test_D2_bootstrap_exit_one_summary(self):
        # A stale Python environment makes real Python initialization exit 1.
        # Real uv and the delivered wrappers must still produce a pasteable failure.
        with self.machine('codex', REAL_UV=True, PYTHONHOME='/nonexistent-prework-python') as (execute, git, base):
            for shell in ('bash', 'powershell'):
                with self.subTest(shell=shell):
                    self.summary(execute(shell), False)


if __name__ == '__main__':
    unittest.main()
