import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { FromWorker, ToWorker } from "../../src/protocol";

/** Stands in for the Pyodide worker: records what it gets, the test answers. */
class FakeWorker {
  static all: FakeWorker[] = [];
  onmessage: ((ev: { data: FromWorker }) => void) | null = null;
  onerror: ((ev: { message: string; preventDefault(): void }) => void) | null = null;
  onmessageerror: (() => void) | null = null;
  sent: ToWorker[] = [];
  terminated = false;
  constructor() {
    FakeWorker.all.push(this);
  }
  postMessage(msg: ToWorker) {
    this.sent.push(msg);
  }
  terminate() {
    this.terminated = true;
  }
  reply(data: FromWorker) {
    this.onmessage?.({ data });
  }
  ready() {
    this.reply({ type: "ready", groups: [], generators: [], loadMs: 1 });
  }
  crash(message = "boom") {
    this.onerror?.({ message, preventDefault() {} });
  }
  /** Id of the last request of this type. */
  last(type: ToWorker["type"]): number {
    const msg = this.sent.filter((m) => m.type === type).pop();
    return msg && "id" in msg ? msg.id : -1;
  }
}

const rendered = (id: number, svg = "<svg/>"): FromWorker => ({
  type: "rendered", id, svg, parts: [], assembly: false, warnings: ["w"],
  dims: [], handles: [], lines: [], thickness: 3, ms: 1,
});

const tick = () => new Promise((r) => setTimeout(r, 0));

let BoxesClient: typeof import("../../src/boxesClient").BoxesClient;

beforeEach(async () => {
  FakeWorker.all = [];
  vi.stubGlobal("Worker", FakeWorker);
  ({ BoxesClient } = await import("../../src/boxesClient"));
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("BoxesClient", () => {
  test("passes the bases to the worker and the render result through, warnings included", async () => {
    const client = new BoxesClient("w/", "p/");
    const w = FakeWorker.all[0];
    expect(w.sent[0]).toEqual({ type: "init", wheelBase: "w/", pyodideBase: "p/" });
    w.ready();
    const result = client.render("ABox", {});
    await tick();
    w.reply(rendered(w.last("render")));
    expect(await result).toMatchObject({ svg: "<svg/>", warnings: ["w"], thickness: 3 });
  });

  test("latest render wins: a queued request that is replaced resolves to null", async () => {
    const client = new BoxesClient("w/", "p/");
    const w = FakeWorker.all[0];
    w.ready();
    const first = client.render("ABox", { x: "1" });
    const second = client.render("ABox", { x: "2" });
    const third = client.render("ABox", { x: "3" });
    await tick();
    w.reply(rendered(w.last("render"), "<svg id='1'/>"));
    expect((await first)?.svg).toBe("<svg id='1'/>");
    expect(await second).toBeNull();
    await tick();
    const msg = w.sent.filter((m) => m.type === "render").pop();
    expect(msg).toMatchObject({ args: { x: "3" } });
    w.reply(rendered(w.last("render")));
    expect(await third).not.toBeNull();
  });

  test("a request over the time limit fails and Python restarts", async () => {
    vi.useFakeTimers();
    const client = new BoxesClient("w/", "p/");
    const restarts: string[] = [];
    client.onRestart = (r) => restarts.push(r);
    client.timeoutMs = 1000;
    const w = FakeWorker.all[0];
    w.ready();
    const slow = client.render("ABox", { x: "200000" });
    const failed = expect(slow).rejects.toThrow(/took too long/);
    await vi.advanceTimersByTimeAsync(1001);
    await failed;
    expect(w.terminated).toBe(true);
    expect(restarts).toHaveLength(1);
    // Requests made now wait for the new worker.
    const next = client.schema("ABox");
    const w2 = FakeWorker.all[1];
    expect(w2.sent[0].type).toBe("init");
    w2.ready();
    await vi.advanceTimersByTimeAsync(0);
    w2.reply({ type: "schema", id: w2.last("schema"), schema: { name: "ABox", doc: "", groups: [] } });
    expect(await next).toMatchObject({ name: "ABox" });
  });

  test("an answer in time clears the timer", async () => {
    vi.useFakeTimers();
    const client = new BoxesClient("w/", "p/");
    client.timeoutMs = 1000;
    const w = FakeWorker.all[0];
    w.ready();
    const r = client.render("ABox", {});
    await vi.advanceTimersByTimeAsync(10);
    w.reply(rendered(w.last("render")));
    await r;
    await vi.advanceTimersByTimeAsync(5000);
    expect(w.terminated).toBe(false);
    expect(FakeWorker.all).toHaveLength(1);
  });

  test("a crash after loading fails the pending requests and restarts", async () => {
    const client = new BoxesClient("w/", "p/");
    const w = FakeWorker.all[0];
    w.ready();
    const r = client.exportFormat("ABox", {}, "svg");
    await tick();
    w.crash("out of memory");
    await expect(r).rejects.toThrow(/crashed: out of memory/);
    expect(FakeWorker.all).toHaveLength(2);
  });

  test("a crash while loading rejects ready and does not restart", async () => {
    const client = new BoxesClient("w/", "p/");
    FakeWorker.all[0].crash("no wasm");
    await expect(client.ready).rejects.toThrow(/no wasm/);
    expect(FakeWorker.all).toHaveLength(1);
  });
});
