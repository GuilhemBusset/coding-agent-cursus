// Browser imports belong to the tooling; setup/ owns the locked installation.
import { createRequire } from 'node:module';

const requireSetup = createRequire(new URL('../../setup/package.json', import.meta.url));
export const { chromium } = requireSetup('playwright');
export const { default: AxeBuilder } = requireSetup('@axe-core/playwright');
