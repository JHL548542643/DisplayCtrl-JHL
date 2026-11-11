import assert from "node:assert/strict";
import test from "node:test";
import { isThemeName, syncNativeTitleBar, type ThemeName } from "./windowTheme.ts";

test("isThemeName accepts only 夜航/石墨/日间 ids", () => {
  assert.equal(isThemeName("night"), true);
  assert.equal(isThemeName("graphite"), true);
  assert.equal(isThemeName("day"), true);
  assert.equal(isThemeName("dark"), false);
  assert.equal(isThemeName(null), false);
  assert.equal(isThemeName(undefined), false);
});

test("syncNativeTitleBar calls set_theme when the pywebview bridge is present", () => {
  const seen: ThemeName[] = [];
  const win = {
    pywebview: {
      api: {
        set_theme(theme: ThemeName) {
          seen.push(theme);
        },
      },
    },
  };
  syncNativeTitleBar("graphite", win);
  syncNativeTitleBar("day", win);
  assert.deepEqual(seen, ["graphite", "day"]);
});

test("syncNativeTitleBar is a no-op in the browser", () => {
  syncNativeTitleBar("night", {});
  syncNativeTitleBar("night", { pywebview: {} });
  syncNativeTitleBar("night", { pywebview: { api: {} } });
});