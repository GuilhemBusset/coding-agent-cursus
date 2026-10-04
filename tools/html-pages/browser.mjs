// Browser imports belong to the tooling; setup/ owns the locked installation.
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const requireSetup = createRequire(new URL('../../setup/package.json', import.meta.url));

// Libraries unpacked in user space by setup/browser-libs.py (ADR 0011) reach only the browser
// process: when CURSUS_BROWSER_LIBS names a copy (or its --dest directory), its library
// directories are prepended to LD_LIBRARY_PATH in the `env` Playwright gives the browser,
// never in this process's environment.
export function browserLibDirs(libs = process.env.CURSUS_BROWSER_LIBS) {
  if (!libs) return [];
  const pointer = path.join(libs, 'current');
  const copy = existsSync(pointer) ? path.join(libs, readFileSync(pointer, 'utf8').trim()) : libs;
  try {
    const { lib_dirs: dirs } = JSON.parse(readFileSync(path.join(copy, 'manifest.json'), 'utf8'));
    return dirs.map(dir => path.resolve(copy, dir));
  } catch {
    throw new Error(`CURSUS_BROWSER_LIBS=${libs} holds no activated library copy; run python3 setup/browser-libs.py --dest ${libs}`);
  }
}

// Before a launch, Playwright checks host libraries with ldd under this process's environment,
// which would reject a browser the unpacked copy makes runnable. Naming the executable it would
// pick skips that check (1.63's check looks for a directory the Chrome for Testing layout no
// longer has, so it passes today). Explicit executables, channels and debug runs are left alone.
export function browserExecutable(options = {}) {
  if (options.executablePath || options.channel || process.env.PWDEBUG) return undefined;
  try {
    const { registry } = requireSetup('playwright-core/lib/coreBundle').registry;
    return registry.findExecutable(options.headless === false ? 'chromium' : 'chromium-headless-shell')?.executablePath();
  } catch {
    return undefined;
  }
}

export function withBrowserLibs(browserType, executable = browserExecutable) {
  const prepare = options => {
    const dirs = browserLibDirs();
    if (!dirs.length) return options;
    const base = options?.env ?? process.env;
    const env = { ...base, LD_LIBRARY_PATH: [...dirs, base.LD_LIBRARY_PATH].filter(Boolean).join(path.delimiter) };
    const executablePath = options?.executablePath ?? executable(options ?? {});
    return { ...options, env, ...(executablePath ? { executablePath } : {}) };
  };
  const launchers = {
    launch: async options => browserType.launch(prepare(options)),
    launchServer: async options => browserType.launchServer(prepare(options)),
    launchPersistentContext: async (userDataDir, options) => browserType.launchPersistentContext(userDataDir, prepare(options)),
  };
  return new Proxy(browserType, {
    get(target, property) {
      if (Object.hasOwn(launchers, property)) return launchers[property];
      const value = Reflect.get(target, property, target);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}

export const chromium = withBrowserLibs(requireSetup('playwright').chromium);
export const { default: AxeBuilder } = requireSetup('@axe-core/playwright');
