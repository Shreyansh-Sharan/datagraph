// The rule dialog: pick a kind from the catalogue (DQX-style check functions), the column it judges
// when it needs one, its parameters as the catalogue declares them, a pass threshold and an owner.
// Used on a table's Data quality view and on the Rules screen, where the table is chosen here too.
import { useEffect, useState } from "react";
import { Button, Dialog, Label, Spinner } from "@/components/ui";
import { useApp } from "@/state/app";
import type { DqKind, DqKindInfo, DqParam, DqRule, RuleInput } from "@/api";

const DIMENSIONS = ["completeness", "uniqueness", "validity", "consistency", "timeliness", "volume"];
const LABEL: Record<string, string> = { values: "Allowed values (comma-separated)", forbidden: "Forbidden values (comma-separated)", pattern: "Pattern (regular expression)", min: "Minimum", max: "Maximum",
  hours: "Fresh within (hours)", ref_table: "Referenced table", ref_column: "Referenced column", predicate: "SQL predicate (true for a good row)", limit: "Limit", value: "Value", days: "Days",
  column2: "Other column", columns: "Columns (comma-separated)", case: "Case", aggr: "Aggregate", op: "Comparison", column: "Column to aggregate", filter: "Filter (SQL condition, optional)" };

/** The stored params as the fields show them (lists as comma-separated text, the rest as text). */
export function paramsToText(p: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(Object.entries(p ?? {}).map(([k, v]) => [k, Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v)]));
}

/** The fields as the API wants them: numbers as numbers, lists as arrays, blanks left out. */
export function textToParams(kind: DqKindInfo | undefined, text: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const prm of kind?.params ?? []) {
    const raw = (text[prm.name] ?? "").trim();
    if (!raw) continue;
    if (prm.type === "list") out[prm.name] = raw.split(",").map(s => s.trim()).filter(Boolean);
    else if (prm.type === "number") out[prm.name] = Number(raw);
    else if (prm.type === "scalar") out[prm.name] = Number.isFinite(Number(raw)) && raw !== "" ? Number(raw) : raw;
    else out[prm.name] = raw;
  }
  return out;
}

export function RuleDialog({ open, initial, presetKind, onClose, columns, kinds, tables, table, onTable, onSave }: {
  open: boolean; initial?: DqRule | null; presetKind?: DqKind; onClose: () => void; columns: string[]; kinds: DqKindInfo[];
  tables?: string[]; table?: string; onTable?: (t: string) => void; onSave: (r: RuleInput) => Promise<void>;
}) {
  const { say } = useApp();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<DqKind>("not_null");
  const [column, setColumn] = useState(columns[0] ?? "");
  const [p, setP] = useState<Record<string, string>>({});
  const [threshold, setThreshold] = useState("0.95");
  const [owner, setOwner] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {   // an edit starts from the rule as it is
    if (!open) return;
    setName(initial?.name ?? ""); setKind(initial?.kind ?? presetKind ?? "not_null"); setColumn(initial?.column_name ?? columns[0] ?? "");
    setP(initial ? paramsToText(initial.params) : {}); setThreshold(initial ? String(initial.threshold) : "0.95"); setOwner(initial?.owner ?? "");
  }, [open, initial?.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!columns.includes(column)) setColumn(columns[0] ?? ""); }, [columns]);   // eslint-disable-line react-hooks/exhaustive-deps
  const info = kinds.find(k => k.kind === kind);
  const needsColumn = info ? info.column : kind !== "row_count" && kind !== "custom" && kind !== "aggregate";
  const byDim = DIMENSIONS.map(d => ({ d, kinds: kinds.filter(k => k.dimension === d) })).filter(x => x.kinds.length);
  const submit = async () => {
    setBusy(true);
    try {
      await onSave({ name: name.trim() || `${info?.label ?? kind}${needsColumn && column ? ` on ${column}` : ""}`, kind, column: needsColumn ? column : null, params: textToParams(info, p), threshold: Number(threshold) || 0.95, owner: owner.trim() || null });
      setName(""); setP({});
    } catch (e) { say(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const field = (prm: DqParam) => {
    const label = LABEL[prm.name === "values" && kind === "not_in_set" ? "forbidden" : prm.name] ?? `${prm.name.replace(/_/g, " ")}${prm.required ? "" : " (optional)"}`;
    const set = (v: string) => setP(x => ({ ...x, [prm.name]: v }));
    if (prm.type.startsWith("enum:")) {
      const opts = prm.type.slice(5).split(",");
      return <div key={prm.name}><Label>{label}</Label><select className="select full" aria-label={label} value={p[prm.name] ?? ""} onChange={e => set(e.target.value)}><option value="">Choose…</option>{opts.map(o => <option key={o} value={o}>{o}</option>)}</select></div>;
    }
    if (prm.type === "column" && columns.length) {
      return <div key={prm.name}><Label>{label}</Label><select className="select full mono" aria-label={label} value={p[prm.name] ?? ""} onChange={e => set(e.target.value)}><option value="">Choose…</option>{columns.map(c => <option key={c} value={c}>{c}</option>)}</select></div>;
    }
    const placeholder = prm.type === "list" ? "A, B, C" : prm.type === "regex" ? "^[A-Z]{2}$" : prm.type === "sql" ? "amount >= 0 AND currency IS NOT NULL" : prm.type === "table" ? "schema.table" : "";
    return <div key={prm.name}><Label>{label}</Label><input className={`input full ${prm.type === "number" ? "mono" : prm.type === "sql" || prm.type === "regex" ? "mono" : ""}`} aria-label={label} placeholder={placeholder} value={p[prm.name] ?? ""} onChange={e => set(e.target.value)} />{prm.help && <div className="muted-2 xs" style={{ marginTop: 3 }}>{prm.help}</div>}</div>;
  };
  const params = info?.params ?? [];
  const main = params.filter(x => x.name !== "filter"), filter = params.find(x => x.name === "filter");
  return (
    <Dialog title={initial ? "Edit rule" : "New rule"} open={open} onClose={onClose} width={560} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={busy || (needsColumn && !column) || (!!tables && !table)} onClick={submit}>{busy && <Spinner />}{initial ? "Save rule" : "Add rule"}</Button></>}>
      <div style={{ display: "grid", gap: 12 }}>
        {tables && <div><Label>Table</Label><select className="select full mono" aria-label="Table" value={table ?? ""} onChange={e => onTable?.(e.target.value)}><option value="">Choose a table…</option>{tables.map(t => <option key={t} value={t}>{t}</option>)}</select></div>}
        <div><Label>Name</Label><input className="input full" aria-label="Rule name" placeholder="What the rule checks" value={name} onChange={e => setName(e.target.value)} /></div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div><Label>Kind</Label>
            <select className="select full" aria-label="Kind" value={kind} onChange={e => { setKind(e.target.value as DqKind); setP({}); }}>
              {byDim.length ? byDim.map(x => <optgroup key={x.d} label={x.d}>{x.kinds.map(k => <option key={k.kind} value={k.kind}>{k.label}</option>)}</optgroup>) : <option value={kind}>{kind}</option>}
            </select>
            {info && <div className="muted-2 xs" style={{ marginTop: 3 }}>{info.help} <span className="mono">· DQX {info.dqx}</span></div>}
          </div>
          {needsColumn && <div><Label>Column</Label><select className="select full mono" aria-label="Column" value={column} onChange={e => setColumn(e.target.value)}>{columns.map(c => <option key={c} value={c}>{c}</option>)}</select></div>}
        </div>
        {main.length > 0 && <div style={{ display: "grid", gridTemplateColumns: main.length > 1 ? "1fr 1fr" : "1fr", gap: 12 }}>{main.map(field)}</div>}
        {filter && field(filter)}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <div><Label>Pass threshold (0 to 1)</Label><input className="input full mono" aria-label="Threshold" value={threshold} onChange={e => setThreshold(e.target.value)} /></div>
          <div><Label>Owner</Label><input className="input full" aria-label="Owner" placeholder="Domain steward" value={owner} onChange={e => setOwner(e.target.value)} /></div>
        </div>
      </div>
    </Dialog>
  );
}
