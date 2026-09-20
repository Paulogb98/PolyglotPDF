import { Fragment, type ReactNode } from "react";
import { t, type Key } from "./index";

/** Like ``t``, but a placeholder can be an element: "Você leu {time} deste livro" with
 *  ``time`` in bold. Text around the placeholders stays plain text. */
export function rich(key: Key, vars: Record<string, ReactNode>): ReactNode {
  const parts = t(key).split(/\{(\w+)\}/g);
  return parts.map((part, index) =>
    index % 2 === 0 ? part : <Fragment key={index}>{part in vars ? vars[part] : `{${part}}`}</Fragment>,
  );
}
