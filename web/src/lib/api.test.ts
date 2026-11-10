import { ApiError, api, request } from "./api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("422 dilempar sebagai ApiError dengan fieldErrors", async () => {
    mockFetch(422, { detail: "Periksa kembali isian form", field_errors: { base_url: "Base URL wajib diisi" } });
    const err = await api.createProfile({} as never).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.fieldErrors).toEqual({ base_url: "Base URL wajib diisi" });
    expect(err.message).toBe("Periksa kembali isian form");
  });

  it("409 membawa detail", async () => {
    mockFetch(409, { detail: "Input manual hanya diterima saat ambil alih" });
    const err = await api.control(3, { command: "input", event: { kind: "click", x: 0.1, y: 0.2 } }).catch((e) => e);
    expect(err.status).toBe(409);
    expect(err.message).toContain("ambil alih");
  });

  it("mengirim body JSON dan path yang benar", async () => {
    const fn = mockFetch(200, { case: {}, warning: null });
    await api.patchCase(5, "TC-PEN-002", { status_final: "Fail" });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/runs/5/cases/TC-PEN-002");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ status_final: "Fail" });
  });

  it("204 mengembalikan undefined", async () => {
    mockFetch(204, undefined);
    await expect(request("/api/apps/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("URL unduhan", () => {
    expect(api.downloadUrl(7, "xlsx")).toBe("/api/runs/7/download/xlsx");
  });
});
