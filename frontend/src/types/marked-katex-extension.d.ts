// The package publishes its TypeScript sources, which would otherwise be type-checked with
// this project's strict settings; tsconfig "paths" points the compiler here instead.
import type { MarkedExtension } from "marked";

export interface MarkedKatexOptions {
  throwOnError?: boolean;
  nonStandard?: boolean;
  output?: "html" | "mathml" | "htmlAndMathml";
  displayMode?: boolean;
  [option: string]: unknown;
}

export default function markedKatex(options?: MarkedKatexOptions): MarkedExtension;
