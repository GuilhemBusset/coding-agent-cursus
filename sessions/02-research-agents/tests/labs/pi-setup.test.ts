import assert from "node:assert/strict";
import test from "node:test";
import { checkPi } from "../../exercises/fixed/check_setup.ts";

test("both local Pi packages load without a provider request", () => {
  assert.doesNotThrow(checkPi);
});
