import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/lib/api";
import type { SkillsResponse } from "@/lib/types";
import { app, renderWithProviders } from "@/test/render";
import { SkillsTab } from "./SettingsSkills";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      listSkills: vi.fn(),
      uploadSkill: vi.fn(),
      patchSkill: vi.fn(),
      deleteSkill: vi.fn(),
      skillText: vi.fn(),
      previewSkills: vi.fn(),
      listApps: vi.fn(),
      appModules: vi.fn(),
    },
  };
});
const mocked = vi.mocked(api);

const data: SkillsResponse = {
  builtin: {
    name: "QA Engineer profesional",
    description: "Cara berpikir dasar agent saat merancang, menjalankan, dan menilai pengujian.",
    topics: ["Equivalence Partitioning dan Boundary Value", "Decision Table dan State Transition", "Pengujian negatif dan error guessing",
      "Test case: pre-condition, langkah, expected", "Severity dan prioritas bug", "Laporan bug yang bisa direproduksi"],
    content: "Kamu bekerja seperti QA engineer profesional.",
  },
  stages: { plan: "Menyusun test case", execute: "Menjalankan test", judge: "Menilai hasil", report: "Menulis laporan" },
  capacity_percent: 22,
  skills: [
    { id: 1, name: "Standar Test Case Kantor", filename: "standar-test-case.docx", pages: 4, chars: 9000, stages: ["plan", "report"],
      stage_labels: ["Menyusun test case", "Menulis laporan"], app_ids: [], app_names: [], active: true },
    { id: 2, name: "Checklist Regresi Rilis", filename: "checklist-regresi.md", pages: 2, chars: 3000, stages: ["execute"],
      stage_labels: ["Menjalankan test"], app_ids: [3], app_names: ["Web HR"], active: false },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocked.listSkills.mockResolvedValue(data);
  mocked.listApps.mockResolvedValue([app]);
  mocked.appModules.mockResolvedValue({ modules: ["Pengguna", "Laporan"], explored: true });
});

describe("Pengaturan > Skill QA (mockup 06)", () => {
  it("skill bawaan, daftar skill tambahan, ringkasan, kapasitas", async () => {
    renderWithProviders(<SkillsTab />);
    expect(await screen.findByText("QA Engineer profesional")).toBeInTheDocument();
    expect(screen.getByText("Bawaan, selalu aktif")).toBeInTheDocument();
    expect(screen.getByText("Decision Table dan State Transition")).toBeInTheDocument();
    expect(screen.getByText("2 file, 1 aktif")).toBeInTheDocument();
    expect(screen.getByText("standar-test-case.docx")).toBeInTheDocument();
    expect(screen.getByText("Semua aplikasi")).toBeInTheDocument();
    expect(screen.getByText("Web HR")).toBeInTheDocument();
    expect(screen.getByText("22%")).toBeInTheDocument();
    expect(screen.getByText("Kapan skill dipakai")).toBeInTheDocument();
  });

  it("Lihat isi skill bawaan", async () => {
    renderWithProviders(<SkillsTab />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Lihat isi/ }));
    expect(screen.getByText(/Kamu bekerja seperti QA engineer profesional/)).toBeInTheDocument();
  });

  it("unggah file skill", async () => {
    mocked.uploadSkill.mockResolvedValue(data.skills[0]);
    renderWithProviders(<SkillsTab />);
    const user = userEvent.setup();
    const file = new File(["# Aturan"], "aturan-cuti.pdf", { type: "application/pdf" });
    await user.upload(await screen.findByLabelText("File skill"), file);
    await waitFor(() => expect(mocked.uploadSkill).toHaveBeenCalledWith(file));
  });

  it("aktif/nonaktif dan ubah tahap pemakaian", async () => {
    mocked.patchSkill.mockResolvedValue(data.skills[1]);
    renderWithProviders(<SkillsTab />);
    const user = userEvent.setup();
    const row = (await screen.findByText("Checklist Regresi Rilis")).closest("li")!;
    await user.click(within(row).getByRole("switch"));
    expect(mocked.patchSkill).toHaveBeenCalledWith(2, { active: true });
    await user.click(within(row).getByRole("button", { name: /Atur skill/ }));
    await user.click(within(row).getByRole("checkbox", { name: "Menilai hasil" }));
    await user.click(within(row).getByRole("button", { name: "Simpan" }));
    await waitFor(() => expect(mocked.patchSkill).toHaveBeenLastCalledWith(2, expect.objectContaining({ stages: ["execute", "judge"] })));
  });

  it("Coba pada modul contoh menampilkan test case hasil susunan AI", async () => {
    mocked.previewSkills.mockResolvedValue({
      cases: [{ id: "TC-PEN-001", title: "Cuti melebihi batas ditolak", steps: ["Ajukan cuti 13 hari"], expected: "Pesan batas cuti" } as never],
    });
    renderWithProviders(<SkillsTab />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Coba pada modul contoh/ }));
    await user.selectOptions(await screen.findByLabelText("Modul contoh"), "Pengguna");
    await user.click(screen.getByRole("button", { name: /Susun test case/ }));
    expect(await screen.findByText("Cuti melebihi batas ditolak")).toBeInTheDocument();
    expect(mocked.previewSkills).toHaveBeenCalledWith({ app_id: 3, module: "Pengguna" });
  });
});
