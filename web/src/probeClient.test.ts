import assert from "node:assert/strict";
import test from "node:test";
import {
  ApiError,
  HEALTH_TIMEOUT_MS,
  LUMINANCE_TIMEOUT_MS,
  MONITORS_TIMEOUT_MS,
  MONITOR_PROBE_RETRY_DELAY_MS,
  probeRefusalCopy,
  shareInflight,
} from "./probeClient.ts";

test("list and luminance waits outlast a multi-monitor dxva2 walk", () => {
  assert.ok(MONITORS_TIMEOUT_MS >= 20_000);
  assert.ok(LUMINANCE_TIMEOUT_MS >= 20_000);
  assert.equal(MONITORS_TIMEOUT_MS, 30_000);
  assert.equal(LUMINANCE_TIMEOUT_MS, 30_000);
  assert.equal(HEALTH_TIMEOUT_MS, 8_000);
  assert.ok(HEALTH_TIMEOUT_MS < MONITORS_TIMEOUT_MS);
  assert.ok(MONITOR_PROBE_RETRY_DELAY_MS > 0);
  assert.ok(MONITOR_PROBE_RETRY_DELAY_MS <= 2_000);
});

test("a client timeout is not the bare 探测失败 string", () => {
  const copy = probeRefusalCopy(new DOMException("The operation was aborted due to timeout", "TimeoutError"));
  assert.match(copy.message, /超时/);
  assert.match(copy.message, /重试/);
  assert.notEqual(copy.message, "探测失败");
  assert.equal(copy.title, "这次没有完成显示器探测");
  assert.equal(copy.retryList, true);
});

test("AbortError from the list timeout signal is treated as a timeout", () => {
  const copy = probeRefusalCopy(new DOMException("The operation was aborted.", "AbortError"));
  assert.equal(copy.retryList, true);
  assert.match(copy.message, /超时/);
});

test("a dropped fetch can retry the list once", () => {
  const copy = probeRefusalCopy(new TypeError("Failed to fetch"));
  assert.equal(copy.retryList, true);
  assert.match(copy.message, /重试/);
  assert.notEqual(copy.message, "探测失败");
});

test("server refusals keep their message and do not auto-retry the list", () => {
  const error = new ApiError({
    kind: "platform_unsupported",
    message: "当前系统不是 Windows，或 dxva2 不可用。没有写入。",
    retryable: false,
  });
  const copy = probeRefusalCopy(error);
  assert.equal(copy.message, error.message);
  assert.equal(copy.title, "这块机器现在不能写显示器");
  assert.equal(copy.retryList, false);
});

test("retryable server errors keep their message and may retry the list", () => {
  const error = new ApiError({
    kind: "transient",
    message: "这次读取超时或忙。没有写入。",
    retryable: true,
  });
  const copy = probeRefusalCopy(error);
  assert.equal(copy.message, error.message);
  assert.equal(copy.retryList, true);
});

test("unknown failures stay visible without an automatic list retry", () => {
  const copy = probeRefusalCopy(new Error("boom"));
  assert.match(copy.message, /重试/);
  assert.notEqual(copy.message, "探测失败");
  assert.equal(copy.retryList, false);
});

test("shareInflight joins overlapping callers and allows a later attempt", async () => {
  const slot: { current: Promise<string> | null } = { current: null };
  let starts = 0;
  const start = () => {
    starts += 1;
    return new Promise<string>((resolve) => {
      setTimeout(() => resolve("ok"), 20);
    });
  };
  const [first, second] = await Promise.all([shareInflight(slot, start), shareInflight(slot, start)]);
  assert.equal(first, "ok");
  assert.equal(second, "ok");
  assert.equal(starts, 1);
  assert.equal(slot.current, null);
  assert.equal(await shareInflight(slot, start), "ok");
  assert.equal(starts, 2);
});

test("a rejected shared probe does not stick in the slot", async () => {
  const slot: { current: Promise<string> | null } = { current: null };
  let starts = 0;
  const start = () => {
    starts += 1;
    return Promise.reject(new Error("no"));
  };
  const [first, second] = await Promise.allSettled([shareInflight(slot, start), shareInflight(slot, start)]);
  assert.equal(first.status, "rejected");
  assert.equal(second.status, "rejected");
  assert.equal(starts, 1);
  assert.equal(slot.current, null);
  await assert.rejects(shareInflight(slot, start), /no/);
  assert.equal(starts, 2);
});
