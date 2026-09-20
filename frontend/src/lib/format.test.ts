import { describe, expect, it } from "vitest";
import { codePoints, formatBytes, languageName, percent, relativeTime } from "./format";

describe("format", () => {
  it("counts code points like the API", () => {
    expect(codePoints("a𝑥b")).toBe(3);
    expect("a𝑥b".length).toBe(4);
  });

  it("formats sizes, percentages and relative times in Portuguese", () => {
    expect(formatBytes(1536)).toBe("1,5 KB");
    expect(formatBytes(512)).toBe("512 B");
    expect(percent(0.426)).toBe("43%");
    const now = Date.parse("2026-09-12T12:00:00Z");
    expect(relativeTime("2026-09-12T10:00:00Z", now)).toBe("há 2 horas");
  });

  it("names languages", () => {
    const languages = [{ code: "pt-BR", name: "Brazilian Portuguese" }];
    expect(languageName("pt-BR", languages)).toBe("Brazilian Portuguese");
    expect(languageName("auto", languages)).toBe("Detectar automaticamente");
    expect(languageName("xx", languages)).toBe("xx");
  });
});
