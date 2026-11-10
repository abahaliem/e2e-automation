import { useEffect, useRef, useState } from "react";
import type { Frame, PlannedEvent, RunEvent, Snapshot, StepEvent } from "./types";

export function backoffDelay(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 10_000);
}

export function parseFrame(data: ArrayBuffer): { meta: { width: number; height: number }; jpeg: Uint8Array } {
  const bytes = new Uint8Array(data);
  if (bytes.length < 5 || bytes[0] !== 0x46) throw new Error("Bukan frame live");
  const size = new DataView(data).getUint32(1);
  const meta = JSON.parse(new TextDecoder().decode(bytes.subarray(5, 5 + size)));
  return { meta, jpeg: bytes.subarray(5 + size) };
}

const stepKey = (s: { tc_id: string; step_no: number }) => `${s.tc_id}#${s.step_no}`;

export function mergeSteps(current: StepEvent[], incoming: StepEvent[]): StepEvent[] {
  const map = new Map<string, StepEvent>();
  for (const s of current) map.set(stepKey(s), s);
  for (const s of incoming) map.set(stepKey(s), s);
  return Array.from(map.values()).slice(-200);
}

function wsUrl(path: string): string {
  const { protocol, host } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${host}${path}`;
}

/** Terapkan event run ke snapshot (sama dengan logika EventHub di server). */
export function applyEvent(snap: Snapshot, event: RunEvent): Snapshot {
  const next: Snapshot = { ...snap, seq: typeof event.seq === "number" ? event.seq : snap.seq };
  switch (event.type) {
    case "run.status":
      next.status = (event.status as Snapshot["status"]) ?? snap.status;
      next.counts = (event.counts as Snapshot["counts"]) ?? snap.counts;
      next.note = (event.note as string) ?? snap.note;
      if (next.status !== "running") next.asking = null;
      break;
    case "control.state":
      next.control_state = event.state as Snapshot["control_state"];
      if ((event.state === "running" || event.state === "stopped") && event.command !== "explore.ask") next.asking = null;
      break;
    case "explore.ask":
      next.asking = {
        screens: Number(event.screens ?? 0),
        modules: Number(event.modules ?? 0),
        ...(typeof event.new_screens === "number" ? { new_screens: event.new_screens } : {}),
      };
      break;
    case "tc.started": {
      const tc_id = event.tc_id as string;
      next.current_tc = tc_id;
      const others = snap.cases.filter((c) => c.tc_id !== tc_id);
      const existing = snap.cases.find((c) => c.tc_id === tc_id);
      next.cases = existing
        ? snap.cases.map((c) => (c.tc_id === tc_id ? { ...c, title: (event.title as string) || c.title, status: null } : c))
        : [...others, { tc_id, title: (event.title as string) ?? "", status: null }];
      break;
    }
    case "tc.finished": {
      const tc_id = event.tc_id as string;
      next.cases = snap.cases.map((c) => (c.tc_id === tc_id ? { ...c, status: (event.status as never) ?? null } : c));
      if (snap.current_tc === tc_id) next.current_tc = null;
      next.planned = null;
      break;
    }
    case "cases.planned":
      next.cases = (event.cases as Snapshot["cases"]) ?? snap.cases;
      break;
    case "step.planned":
      next.planned = event as unknown as PlannedEvent;
      next.awaiting_confirm = Boolean(snap.confirm_each_step);
      break;
    case "step.done":
      if (snap.planned && snap.planned.tc_id === event.tc_id && snap.planned.step_no === event.step_no) next.planned = null;
      next.awaiting_confirm = false;
      next.steps = mergeSteps(snap.steps, [event as unknown as StepEvent]);
      break;
    case "screen.added":
      next.screens = (snap.screens ?? 0) + 1;
      break;
  }
  return next;
}

export interface RunStream {
  snapshot: Snapshot | null;
  steps: StepEvent[];
  events: RunEvent[];
  frame: Frame | null;
  connected: boolean;
}

export function useRunStream(runId: number | null): RunStream {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [connected, setConnected] = useState(false);
  const seqRef = useRef(0);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    if (runId == null) return;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let disposed = false;

    const connect = () => {
      socket = new WebSocket(wsUrl(`/ws/runs/${runId}`));
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (e: MessageEvent) => {
        if (typeof e.data !== "string") {
          try {
            const { meta, jpeg } = parseFrame(e.data as ArrayBuffer);
            const url = URL.createObjectURL(new Blob([jpeg as BlobPart], { type: "image/jpeg" }));
            if (urlRef.current) URL.revokeObjectURL(urlRef.current);
            urlRef.current = url;
            setFrame({ url, width: meta.width, height: meta.height });
          } catch {
            /* abaikan frame rusak */
          }
          return;
        }
        let msg: RunEvent;
        try {
          msg = JSON.parse(e.data);
        } catch {
          return;
        }
        if (msg.type === "pong") return;
        if (msg.type === "snapshot") {
          const snap = msg as unknown as Snapshot;
          seqRef.current = snap.seq;
          setSnapshot({ ...snap, steps: mergeSteps([], snap.steps ?? []), cases: snap.cases ?? [] });
          return;
        }
        if (typeof msg.seq === "number") {
          if (msg.seq <= seqRef.current) return; // sudah termasuk di snapshot
          seqRef.current = msg.seq;
        }
        setSnapshot((prev) => (prev ? applyEvent(prev, msg) : prev));
        setEvents((prev) => [...prev.slice(-199), msg]);
      };
      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        timer = setTimeout(connect, backoffDelay(attempt));
        attempt += 1;
      };
      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();
    const ping = setInterval(() => {
      if (socket && (socket as WebSocket).readyState === 1) socket.send(JSON.stringify({ type: "ping" }));
    }, 25_000);

    return () => {
      disposed = true;
      clearInterval(ping);
      if (timer) clearTimeout(timer);
      socket?.close();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    };
  }, [runId]);

  return { snapshot, steps: snapshot?.steps ?? [], events, frame, connected };
}

/** Status run global (kartu "Sedang berjalan" di Dashboard). */
export function useGlobalEvents(onEvent: (event: RunEvent) => void): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let disposed = false;
    const connect = () => {
      socket = new WebSocket(wsUrl("/ws/events"));
      socket.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      socket.onmessage = (e: MessageEvent) => {
        if (typeof e.data !== "string") return;
        try {
          const msg = JSON.parse(e.data);
          if (msg.type !== "pong") handler.current(msg);
        } catch {
          /* abaikan */
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        timer = setTimeout(connect, backoffDelay(attempt));
        attempt += 1;
      };
    };
    connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, []);
  return connected;
}
