import { describe, expect, it } from "vitest";
import type { LayerWord } from "../../api/types";
import { cleanCopy, compareAnchors, rangeRects } from "./textLayer";

const WORDS: LayerWord[] = [
  [10, 10, 30, 20, 0, "The "],
  [34, 10, 60, 20, 4, "quick "],
  [64, 10, 90, 20, 10, "fox "],
  [10, 30, 40, 40, 14, "jumps"],
];

describe("rangeRects", () => {
  it("covers the words of a range, one rectangle per line", () => {
    expect(rangeRects(WORDS, 5, 16)).toEqual([
      [34, 10, 90, 20],
      [10, 30, 40, 40],
    ]);
  });

  it("ignores the spaces after a word", () => {
    expect(rangeRects(WORDS, 3, 4)).toEqual([]);
    expect(rangeRects(WORDS, 0, 1)).toEqual([[10, 10, 30, 20]]);
  });
});

describe("helpers", () => {
  it("orders anchors by page and offset", () => {
    expect(compareAnchors({ page: 1, offset: 0 }, { page: 0, offset: 99 })).toBeGreaterThan(0);
    expect(compareAnchors({ page: 2, offset: 5 }, { page: 2, offset: 9 })).toBeLessThan(0);
  });

  it("joins words hyphenated at the end of a line when copying", () => {
    expect(cleanCopy("an exam- ple  of\ntext")).toBe("an example of text");
    expect(cleanCopy("Rio- Grande")).toBe("Rio- Grande");
  });
});
