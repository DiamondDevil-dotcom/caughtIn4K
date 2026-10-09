import test from "node:test";
import assert from "node:assert/strict";
import { parseSetupLabel } from "./setup-label.js";

const label = { version: 1, gateway_id: "11111111-2222-3333-4444-555555555555", pairing_code: "test-code" };
test("valid setup label retains only the one-time pairing secret", () => {
  assert.deepEqual(parseSetupLabel(JSON.stringify(label)), label);
});
test("invalid, oversized or machine-secret labels are rejected", () => {
  for (const value of [
    "", "null", "[]", "{}", "x".repeat(2049),
    JSON.stringify({ ...label, version: 2 }),
    JSON.stringify({ ...label, gateway_id: "not-a-gateway" }),
    JSON.stringify({ ...label, pairing_code: " " }),
    JSON.stringify({ ...label, gateway_credential: "machine-secret" }),
  ]) assert.throws(() => parseSetupLabel(value));
});
