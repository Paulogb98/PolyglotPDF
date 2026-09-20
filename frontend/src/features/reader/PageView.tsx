import { useEffect, useRef, useState } from "react";
import { urls } from "../../api/client";
import type { Anchor, HighlightInk, Mark, Rect, TextLayer } from "../../api/types";
import { buildTextLayer, loadTextLayer, rangeRects } from "./textLayer";
import { t } from "../../i18n";

export interface PageHit {
  rects: Rect[];
  current: boolean;
}

/** The passage an open conversation is about: it stays tinted while the conversation lives. */
export interface Focus {
  start: Anchor;
  end: Anchor;
}

/** The resolution a page image is asked for at a display ``scale``: sharp on high-density
 *  screens and when zoomed in, in quarter steps so resizing reuses cached images. */
export function imageScale(scale: number): number {
  const density = Math.max(1.6, (window.devicePixelRatio || 1) * 1.25);
  const wanted = Math.min(4.5, Math.max(1, scale * density));
  return Math.ceil(wanted * 4) / 4;
}

function span(page: number, start: Anchor, end: Anchor): [number, number] {
  return [
    start.page === page ? start.offset : 0,
    end.page === page ? end.offset : Number.MAX_SAFE_INTEGER,
  ];
}

/** One page: its image, the transparent text layer, the ink, and the marks in its margin. */
export function PageView({
  documentId,
  page,
  version,
  width,
  height,
  scale,
  side,
  marks,
  hits,
  focus,
  ink,
  onMarkClick,
}: {
  documentId: string;
  page: number;
  version: string | null;
  width: number;
  height: number;
  scale: number;
  /** Which leaf the page is: its outer margin is where the marks go. */
  side: "left" | "right" | "single";
  marks: Mark[];
  hits: PageHit[];
  focus: Focus | null;
  ink(color: string): HighlightInk;
  onMarkClick?(mark: Mark): void;
}) {
  const textRef = useRef<HTMLDivElement>(null);
  const [layer, setLayer] = useState<TextLayer | null>(null);
  const [imageReady, setImageReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLayer(null);
    void loadTextLayer(documentId, page, version)
      .then((loaded) => !cancelled && setLayer(loaded))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [documentId, page, version]);

  useEffect(() => {
    if (layer && textRef.current) buildTextLayer(textRef.current, layer);
  }, [layer]);

  const source = layer ?? { width, height, words: [] as TextLayer["words"] };
  const factor = source.width ? (width * scale) / source.width : scale;
  const pixelWidth = width * scale;
  const outer = (inset: number) =>
    side === "left" ? { left: inset } : { left: pixelWidth - inset };

  return (
    <div
      className="page"
      style={{ width: pixelWidth, height: height * scale }}
      data-page={page}
      data-version={version ?? ""}
    >
      <img
        src={urls.pageImage(documentId, page, imageScale(scale), version)}
        alt=""
        draggable={false}
        onLoad={() => setImageReady(true)}
      />
      {!imageReady ? <div className="page-loading">carregando…</div> : null}

      <div
        className="mark-layer"
        style={{ width: source.width, height: source.height, transform: `scale(${factor})` }}
      >
        {layer && focus
          ? rangeRects(layer.words, ...span(page, focus.start, focus.end)).map((rect, index) => (
              <i
                key={`focus-${index}`}
                className="asked"
                style={{
                  left: rect[0],
                  top: rect[1],
                  width: rect[2] - rect[0],
                  height: rect[3] - rect[1],
                }}
              />
            ))
          : null}
        {layer
          ? marks
              .filter((mark) => mark.source === "reader")
              .flatMap((mark) => {
                const paint = ink(mark.color);
                return rangeRects(layer.words, ...span(page, mark.start, mark.end)).map(
                  (rect, index) => (
                    <i
                      key={`${mark.id}-${index}`}
                      className="ink"
                      style={{
                        left: rect[0],
                        top: rect[1],
                        width: rect[2] - rect[0],
                        height: rect[3] - rect[1],
                        backgroundImage: `linear-gradient(${paint.ink}, ${paint.ink})`,
                      }}
                    />
                  ),
                );
              })
          : null}
        {hits.flatMap((hit, group) =>
          hit.rects.map((rect, index) => (
            <i
              key={`hit-${group}-${index}`}
              className={`hit ${hit.current ? "current" : ""}`}
              style={{
                left: rect[0],
                top: rect[1],
                width: rect[2] - rect[0],
                height: rect[3] - rect[1],
              }}
            />
          )),
        )}
      </div>

      <div
        className="text-layer"
        ref={textRef}
        style={{ width: source.width, height: source.height, transform: `scale(${factor})` }}
      />

      {layer && onMarkClick
        ? marks
            .filter((mark) => mark.source === "tutor" || mark.kind === "note")
            .map((mark) => {
              const rects = rangeRects(layer.words, ...span(page, mark.start, mark.end));
              if (!rects.length) return null;
              const top = Math.min(...rects.map((rect) => rect[1])) * factor;
              const bottom = Math.max(...rects.map((rect) => rect[3])) * factor;
              if (mark.source === "tutor") {
                const bar = <span className="bar" style={{ height: Math.max(18, bottom - top) }} />;
                const pip = <span className="pip" />;
                return (
                  <button
                    key={`marker-${mark.id}`}
                    type="button"
                    className={`tutor-mark ${side === "left" ? "" : "left"}`}
                    style={{ top, ...outer(side === "left" ? 18 : 16) }}
                    aria-label={t("page.dense")}
                    onClick={() => onMarkClick(mark)}
                  >
                    {side === "left" ? (
                      <>
                        {bar}
                        {pip}
                      </>
                    ) : (
                      <>
                        {pip}
                        {bar}
                      </>
                    )}
                  </button>
                );
              }
              return (
                <button
                  key={`marker-${mark.id}`}
                  type="button"
                  className="margin-dot"
                  style={{ top: top + 8, ...outer(18) }}
                  aria-label={t("page.openNote")}
                  onClick={() => onMarkClick(mark)}
                />
              );
            })
        : null}
    </div>
  );
}
