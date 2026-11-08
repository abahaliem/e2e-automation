import { ArrowCounterClockwise, ChatCenteredText, CheckCircle, Keyboard, PaperPlaneTilt, Play, SkipForward, XCircle } from "@phosphor-icons/react";
import { useState, type FormEvent } from "react";
import type { ControlInput, ControlState } from "@/lib/types";
import { Button, Textarea } from "./ui";

export function InterventionPanel({
  controlState,
  awaitingConfirm,
  confirmEachStep,
  active,
  onCommand,
}: {
  controlState: ControlState | null;
  awaitingConfirm: boolean;
  confirmEachStep: boolean;
  active: boolean;
  onCommand: (cmd: ControlInput) => Promise<unknown> | void;
}) {
  const [hint, setHint] = useState("");
  const [typed, setTyped] = useState("");
  const [note, setNote] = useState("");
  const alive = active && controlState !== null && controlState !== "stopped";
  const takeover = controlState === "takeover";

  const sendHint = async (e: FormEvent) => {
    e.preventDefault();
    const text = hint.trim();
    if (!text) return;
    await onCommand({ command: "hint", text });
    setHint("");
  };

  const sendText = async () => {
    if (!typed) return;
    await onCommand({ command: "input", event: { kind: "type", text: typed } });
    setTyped("");
  };

  return (
    <div className="flex flex-col gap-3 border-t border-ink-700 bg-ink-850 p-5">
      {confirmEachStep && awaitingConfirm && alive && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-accent-line bg-accent-soft px-3 py-2.5 text-sm">
          <span>Agent menunggu persetujuan untuk langkah berikutnya.</span>
          <Button variant="primary" size="sm" onClick={() => onCommand({ command: "confirm_step" })}>
            <Play weight="fill" />
            Jalankan langkah
          </Button>
        </div>
      )}

      {takeover && (
        <div className="flex flex-col gap-3 rounded-lg border border-accent-line bg-ink-900 p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Keyboard className="text-accent" />
            Kendali manual
          </div>
          <p className="text-xs text-fg-muted">Klik langsung di layar live. Ketik teks atau tekan tombol di bawah.</p>
          <div className="flex gap-2">
            <input
              aria-label="Ketik ke halaman"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void sendText();
                }
              }}
              className="h-9 min-w-0 flex-1 rounded-lg border border-ink-600 bg-ink-900 px-3 text-sm focus:border-accent focus:outline-none"
            />
            <Button size="sm" className="h-9" onClick={sendText}>
              Ketik
            </Button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {["Enter", "Tab", "Escape", "Backspace"].map((key) => (
              <Button key={key} size="sm" variant="outline" onClick={() => onCommand({ command: "input", event: { kind: "key", key } })}>
                {key}
              </Button>
            ))}
          </div>
          <input
            aria-label="Catatan hasil manual"
            placeholder="Catatan (opsional), mis. tombol tidak merespons"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="h-9 rounded-lg border border-ink-600 bg-ink-900 px-3 text-sm focus:border-accent focus:outline-none"
          />
          <div className="flex gap-2">
            <Button size="sm" className="flex-1 border-pass/40 text-pass" onClick={() => onCommand({ command: "end_case", status: "pass", note })}>
              <CheckCircle weight="fill" />
              Akhiri: Pass
            </Button>
            <Button size="sm" variant="danger" className="flex-1" onClick={() => onCommand({ command: "end_case", status: "fail", note })}>
              <XCircle weight="fill" />
              Akhiri: Fail
            </Button>
          </div>
        </div>
      )}

      <form onSubmit={sendHint} className="flex flex-col gap-3">
        <label htmlFor="hint" className="flex items-center gap-2 text-sm font-medium">
          <ChatCenteredText className="text-accent" />
          Arahkan agent
        </label>
        <Textarea
          id="hint"
          rows={3}
          value={hint}
          disabled={!alive}
          placeholder="Contoh: setelah simpan, cek juga apakah nama muncul di halaman daftar pengguna"
          onChange={(e) => setHint(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" disabled={!alive || !hint.trim()}>
            <PaperPlaneTilt />
            Kirim
          </Button>
          <Button
            disabled={!alive || controlState !== "paused"}
            title={controlState === "paused" ? undefined : "Jeda run dulu untuk memakai Pikir ulang"}
            onClick={() => onCommand({ command: "think_again" })}
          >
            <ArrowCounterClockwise />
            Pikir ulang
          </Button>
          <Button disabled={!alive} onClick={() => onCommand({ command: "skip" })}>
            <SkipForward />
            Lewati
          </Button>
        </div>
      </form>
    </div>
  );
}
