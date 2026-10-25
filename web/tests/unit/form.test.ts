import { expect, test } from "vitest";
import { selectValue } from "../../src/form";
import type { ArgSchema } from "../../src/protocol";

const arg = (def: string): ArgSchema & { kind: "select" } => ({
  name: "style", label: "Style", help: "", kind: "select", default: def,
  options: [["a", "A"], ["b", "B"]],
});

test("a select keeps a valid value and falls back to the default otherwise", () => {
  expect(selectValue(arg("b"), "a")).toBe("a");
  expect(selectValue(arg("b"), "nope")).toBe("b");
  expect(selectValue(arg("b"), "")).toBe("b");
  // A default that is not an option: the first option.
  expect(selectValue(arg("zzz"), "nope")).toBe("a");
});
