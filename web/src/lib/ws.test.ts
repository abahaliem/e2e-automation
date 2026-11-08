import { act, renderHook } from "@testing-library/react";
import { backoffDelay, mergeSteps, parseFrame, useRunStream } from "./ws";

function frameBytes(meta: object, jpeg: number[]): ArrayBuffer {
  const raw = new TextEncoder().encode(JSON.stringify(meta));
  const buf = new Uint8Array(1 + 4 + raw.length + jpeg.length);
  buf[0] = "F".charCodeAt(0);
  new DataView(buf.buffer).setUint32(1, raw.length);
  buf.set(raw, 5);
  buf.set(jpeg, 5 + raw.length);
  return buf.buffer;
}

class FakeSocket {
  static instances: FakeSocket[] = [];
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closed = false;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
  emit(data: unknown) {
    this.onmessage?.({ data });
  }
}

describe("parseFrame", () => {
  it("memisahkan meta dan jpeg", () => {
    const { meta, jpeg } = parseFrame(frameBytes({ width: 1366, height: 768 }, [0xff, 0xd8, 1, 2]));
    expect(meta).toEqual({ width: 1366, height: 768 });
    expect(Array.from(jpeg)).toEqual([0xff, 0xd8, 1, 2]);
  });

  it("menolak data yang bukan frame", () => {
    expect(() => parseFrame(new Uint8Array([1, 2, 3]).buffer)).toThrow();
  });
});

describe("backoff", () => {
  it("1s, 2s, 4s, maks 10s", () => {
    expect([0, 1, 2, 3, 4, 8].map(backoffDelay)).toEqual([1000, 2000, 4000, 8000, 10000, 10000]);
  });
});

describe("mergeSteps", () => {
  it("tidak menggandakan langkah dengan id sama", () => {
    const a = { type: "step.done", tc_id: "TC-1", step_no: 1, result: "ok", description: "a" } as const;
    const b = { ...a, step_no: 2 };
    const merged = mergeSteps([a as never, b as never], [{ ...b, result: "error" } as never]);
    expect(merged.map((s) => s.step_no)).toEqual([1, 2]);
    expect(merged[1].result).toBe("error");
  });
});

describe("useRunStream", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:1"), revokeObjectURL: vi.fn() }));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const snap = (seq: number, steps: number[]) => ({
    type: "snapshot",
    run_id: 1,
    seq,
    status: "running",
    control_state: "running",
    steps: steps.map((n) => ({ type: "step.done", tc_id: "TC-1", step_no: n, result: "ok", description: `L${n}` })),
    cases: [],
  });

  it("reconnect mengambil snapshot ulang tanpa langkah ganda", () => {
    const { result } = renderHook(() => useRunStream(1));
    const ws1 = FakeSocket.instances[0];
    expect(ws1.url).toContain("/ws/runs/1");
    act(() => {
      ws1.onopen?.();
      ws1.emit(JSON.stringify(snap(2, [1])));
      ws1.emit(JSON.stringify({ type: "step.done", tc_id: "TC-1", step_no: 2, result: "ok", description: "L2", seq: 3 }));
    });
    expect(result.current.connected).toBe(true);
    expect(result.current.steps.map((s) => s.step_no)).toEqual([1, 2]);

    act(() => ws1.onclose?.());
    expect(result.current.connected).toBe(false);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const ws2 = FakeSocket.instances[1];
    expect(ws2).toBeDefined();
    act(() => {
      ws2.onopen?.();
      ws2.emit(JSON.stringify(snap(4, [1, 2, 3])));
      // event lama yang sudah ada di snapshot diabaikan
      ws2.emit(JSON.stringify({ type: "step.done", tc_id: "TC-1", step_no: 3, result: "ok", description: "L3", seq: 4 }));
    });
    expect(result.current.steps.map((s) => s.step_no)).toEqual([1, 2, 3]);
    expect(result.current.snapshot?.seq).toBe(4);
  });

  it("frame biner menjadi object URL dan URL lama di-revoke", () => {
    const { result } = renderHook(() => useRunStream(1));
    const ws = FakeSocket.instances[0];
    act(() => {
      ws.onopen?.();
      ws.emit(frameBytes({ width: 100, height: 50 }, [0xff, 0xd8]));
      ws.emit(frameBytes({ width: 100, height: 50 }, [0xff, 0xd8]));
    });
    expect(result.current.frame).toEqual({ url: "blob:1", width: 100, height: 50 });
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("menerapkan event status dan kontrol ke snapshot", () => {
    const { result } = renderHook(() => useRunStream(1));
    const ws = FakeSocket.instances[0];
    act(() => {
      ws.onopen?.();
      ws.emit(JSON.stringify(snap(1, [])));
      ws.emit(JSON.stringify({ type: "control.state", state: "paused", seq: 2 }));
      ws.emit(JSON.stringify({ type: "tc.started", tc_id: "TC-1", title: "Login", seq: 3 }));
    });
    expect(result.current.snapshot?.control_state).toBe("paused");
    expect(result.current.snapshot?.current_tc).toBe("TC-1");
    expect(result.current.snapshot?.cases[0]).toEqual({ tc_id: "TC-1", title: "Login", status: null });
  });
});
