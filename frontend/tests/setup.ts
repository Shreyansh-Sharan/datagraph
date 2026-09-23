import "@testing-library/jest-dom/vitest";

// React Flow measures the pane and every node with ResizeObserver and offsetWidth/offsetHeight,
// which jsdom lacks: give elements a plausible size and report it once they are observed.
for (const [prop, fallback] of [["offsetWidth", 800], ["offsetHeight", 600]] as const) {
  Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get(this: HTMLElement) { const own = parseFloat(this.style[prop === "offsetWidth" ? "width" : "height"]); if (own) return own; return this.classList.contains("react-flow__node") ? (prop === "offsetWidth" ? 120 : 34) : fallback; } });
}
class ResizeObserverStub {
  constructor(private cb: (entries: unknown[]) => void) {}
  observe(el: Element) { setTimeout(() => this.cb([{ target: el, contentRect: { width: (el as HTMLElement).offsetWidth, height: (el as HTMLElement).offsetHeight } }]), 0); }
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver ??= ResizeObserverStub;
if (!("DOMMatrixReadOnly" in globalThis)) {
  class DOMMatrixReadOnlyStub { m22 = 1; constructor(_t?: string) {} }
  (globalThis as unknown as { DOMMatrixReadOnly: typeof DOMMatrixReadOnlyStub }).DOMMatrixReadOnly = DOMMatrixReadOnlyStub;
}
// Edge labels measure themselves with getBBox, which jsdom's SVG does not implement.
if (!("getBBox" in SVGElement.prototype)) {
  (SVGElement.prototype as unknown as { getBBox: () => DOMRect }).getBBox = () => ({ x: 0, y: 0, width: 40, height: 12, top: 0, left: 0, right: 40, bottom: 12, toJSON: () => ({}) } as DOMRect);
}
