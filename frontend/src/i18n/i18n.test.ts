import { describe, expect, it } from "vitest";
import { en } from "./en";
import { lang, resolveLang, setLang, t, tn } from "./index";
import { pt } from "./pt";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

describe("the two languages", () => {
  it("have the same keys and fill the same placeholders", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(pt).sort());
    for (const key of Object.keys(pt) as (keyof typeof pt)[]) {
      expect(placeholders(en[key]), key).toEqual(placeholders(pt[key]));
    }
  });

  it("switch what t() and tn() say", () => {
    setLang("en");
    expect(lang()).toBe("en");
    expect(t("common.pageOf", { page: 3, pages: 12 })).toBe("p. 3 of 12");
    expect(tn("common.pages", 1)).toBe("1 page");
    expect(tn("common.pages", 1200)).toBe("1,200 pages");
    setLang("pt-BR");
    expect(t("common.pageOf", { page: 3, pages: 12 })).toBe("p. 3 de 12");
    expect(tn("common.pages", 1200)).toBe("1.200 páginas");
  });

  it("resolve “auto” to a language the interface has", () => {
    expect(resolveLang("en")).toBe("en");
    expect(resolveLang("pt-BR")).toBe("pt-BR");
    expect(["pt-BR", "en"]).toContain(resolveLang("auto"));
  });
});
