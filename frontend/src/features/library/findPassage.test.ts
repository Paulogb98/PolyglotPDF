import { describe, expect, it } from "vitest";
import { keywords } from "./findPassage";

describe("keywords", () => {
  it("keeps the words worth searching for, longest first", () => {
    expect(keywords("Onde Hegel fala que o começo já é resultado?")).toEqual([
      "resultado",
      "começo",
      "hegel",
    ]);
  });

  it("drops the short words and the ones that carry no meaning", () => {
    expect(keywords("o que é isso")).toEqual([]);
  });

  it("never sends more than four words to the search", () => {
    expect(
      keywords("mediação imediatez determinidade quantidade qualidade medida").length,
    ).toBe(4);
  });

  it("counts a repeated word once", () => {
    expect(keywords("começo começo começo")).toEqual(["começo"]);
  });
});
