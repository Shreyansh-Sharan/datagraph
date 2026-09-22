// The assistant writes Markdown; this renders it (sanitised) and turns every ```chart block into a Chart.
import { useMemo } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { Chart, parseChart } from "@/components/Chart";

const FENCE = /```chart\s*\n([\s\S]*?)```/g;

type Segment = { kind: "md"; text: string } | { kind: "chart"; text: string };

export function splitCharts(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(FENCE)) {
    if (m.index! > last) out.push({ kind: "md", text: text.slice(last, m.index) });
    out.push({ kind: "chart", text: m[1] });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ kind: "md", text: text.slice(last) });
  return out;
}

export function renderMarkdown(text: string): string {
  const html = marked.parse(text, { gfm: true, breaks: true, async: false }) as string;
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

export function Markdown({ text }: { text: string }) {
  const segments = useMemo(() => splitCharts(text), [text]);
  return (
    <div className="md">
      {segments.map((s, i) => {
        if (s.kind === "chart") {
          const spec = parseChart(s.text);
          return spec ? <Chart key={i} spec={spec} /> : <pre key={i}>{s.text}</pre>;
        }
        return <div key={i} dangerouslySetInnerHTML={{ __html: renderMarkdown(s.text) }} />;
      })}
    </div>
  );
}
