/**
 * Plugin Vite: kumpulkan kelas Tailwind dari src/ dan berikan ke Tailwind lewat `@source inline(...)`.
 *
 * Alasan: di laptop kantor, binary native Tailwind (oxide .node) dihapus oleh antivirus sehingga Tailwind
 * memakai fallback WASI yang tidak bisa membaca file. Pemindaian berbasis konten (scanFiles) tetap berfungsi,
 * jadi file dibaca oleh Node lalu isinya diberikan ke scanner. Hasilnya ditulis ke src/tw-candidates.css
 * (dibuat otomatis, di-gitignore).
 */
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import type { Plugin } from "vite";

const require = createRequire(import.meta.url);

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

export function generateCandidates(root: string): string {
  const { Scanner } = require("@tailwindcss/oxide") as typeof import("@tailwindcss/oxide");
  const src = path.join(root, "src");
  const files = [path.join(root, "index.html"), ...walk(src)].filter(
    (f) => /\.(tsx?|html)$/.test(f) && !/\.test\.tsx?$/.test(f) && fs.existsSync(f),
  );
  const scanner = new Scanner({});
  const candidates = scanner
    .scanFiles(files.map((f) => ({ content: fs.readFileSync(f, "utf8"), extension: path.extname(f).slice(1) })))
    .filter((c) => !/[{}"'\\\s]/.test(c))
    .sort();
  const body =
    "/* Dibuat otomatis oleh web/tw-candidates.ts. Jangan diedit. */\n" +
    `@source inline("${Array.from(new Set(candidates)).join(" ")}");\n`;
  const out = path.join(src, "tw-candidates.css");
  if (!fs.existsSync(out) || fs.readFileSync(out, "utf8") !== body) fs.writeFileSync(out, body);
  return out;
}

export function tailwindCandidates(root: string): Plugin {
  return {
    name: "qa-agent-tailwind-candidates",
    enforce: "pre",
    buildStart() {
      generateCandidates(root);
    },
    handleHotUpdate(ctx) {
      if (/\.(tsx?|html)$/.test(ctx.file) && !ctx.file.endsWith("tw-candidates.css")) generateCandidates(root);
    },
  };
}
