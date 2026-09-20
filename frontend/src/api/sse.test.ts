import { describe, expect, it } from "vitest";
import { parseEvent } from "./sse";

describe("parseEvent", () => {
  it("reads the event name and its JSON data", () => {
    expect(parseEvent('event: delta\ndata: {"text":"Olá"}')).toEqual({
      event: "delta",
      data: { text: "Olá" },
    });
  });

  it("joins multi-line data and ignores blocks without data", () => {
    expect(parseEvent("event: x\ndata: [1,\ndata: 2]")).toEqual({ event: "x", data: [1, 2] });
    expect(parseEvent(": keep-alive")).toBeNull();
    expect(parseEvent("data: not json")).toBeNull();
  });
});
