import { useEffect, type CSSProperties, type ReactNode } from "react";
import { STATUS_COLOR, STATUS_LABEL, type VersionStatus } from "@/api";
import { Icon } from "./icons";

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "outline" | "danger" | "ghost" | "danger-text"; size?: "md" | "sm" | "xs" | "xxs"; active?: boolean; pill?: boolean; dashed?: boolean };
export function Button({ variant = "default", size = "md", active, pill, dashed, className = "", children, ...rest }: BtnProps) {
  const cls = ["btn", variant !== "default" ? variant : "", size !== "md" ? size : "", active ? "active" : "", pill ? "pill" : "", dashed ? "dashed" : "", className].filter(Boolean).join(" ");
  return <button type="button" className={cls} {...rest}>{children}</button>;
}

export function PageHead({ title, intro, children }: { title: ReactNode; intro?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{intro && <p>{intro}</p>}</div>
      {children && <div className="actions">{children}</div>}
    </div>
  );
}

export function Card({ children, className = "", style, flush }: { children: ReactNode; className?: string; style?: CSSProperties; flush?: boolean }) {
  return <div className={`card ${flush ? "flush" : ""} ${className}`} style={style}>{children}</div>;
}

export function Dot({ color, size = 7, style, title }: { color: string; size?: number; style?: CSSProperties; title?: string }) {
  return <i className="dot" title={title} style={{ background: color, width: size, height: size, ...style }} />;
}

export function Pill({ dot, children, tone, size, style, onClick, title }: { dot?: string; children: ReactNode; tone?: "blue" | "outline" | "warn" | "solid" | "mini"; size?: "lg"; style?: CSSProperties; onClick?: () => void; title?: string }) {
  const cls = ["pill", tone ?? "", size ?? ""].filter(Boolean).join(" ");
  const inner = <>{dot && <Dot color={dot} />}{children}</>;
  return onClick ? <a href="#" className={cls} style={style} title={title} onClick={e => { e.preventDefault(); onClick(); }}>{inner}</a> : <span className={cls} style={style} title={title}>{inner}</span>;
}

export function StatusPill({ status }: { status: VersionStatus }) {
  return <Pill dot={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Pill>;
}

export function Glyph({ children, color = "#2249FF", size = 24, fontSize = 11 }: { children: ReactNode; color?: string; size?: number; fontSize?: number }) {
  return <span className="glyph" style={{ width: size, height: size, background: color, fontSize }}>{children}</span>;
}

export function Tabs<T extends string>({ items, value, onChange, pad }: { items: { id: T; label: string; count?: number | string | false; countStyle?: CSSProperties }[]; value: T; onChange: (id: T) => void; pad?: boolean }) {
  return (
    <div className={`tabs ${pad ? "pad" : ""}`} role="tablist">
      {items.map(t => (
        <button key={t.id} type="button" role="tab" className="tab" aria-selected={t.id === value} onClick={() => onChange(t.id)}>
          {t.label}{t.count !== undefined && t.count !== false && <span className="count" style={t.countStyle}>{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function KV({ k, v, mono = true }: { k: ReactNode; v: ReactNode; mono?: boolean }) {
  return <div className="kv"><span className="k">{k}</span><span className={mono ? "v" : "v"} style={mono ? undefined : { fontFamily: "inherit" }}>{v}</span></div>;
}

export function Label({ children, block = true }: { children: ReactNode; block?: boolean }) {
  return <label className={`label-caps ${block ? "block" : ""}`}>{children}</label>;
}

export function GridHead({ cols, children, style }: { cols: string; children: ReactNode; style?: CSSProperties }) {
  return <div className="grid-head" style={{ gridTemplateColumns: cols, ...style }}>{children}</div>;
}
export function GridRow({ cols, children, onClick, hover, style }: { cols: string; children: ReactNode; onClick?: () => void; hover?: boolean; style?: CSSProperties }) {
  if (onClick) return <a href="#" className="grid-row link" style={{ gridTemplateColumns: cols, ...style }} onClick={e => { e.preventDefault(); onClick(); }}>{children}</a>;
  return <div className={`grid-row ${hover ? "hover" : ""}`} style={{ gridTemplateColumns: cols, ...style }}>{children}</div>;
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label?: string }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} className={`toggle ${on ? "on" : ""}`} onClick={() => onChange(!on)}><i /></button>;
}

export function Spinner({ blue }: { blue?: boolean }) { return <i className={`spinner ${blue ? "blue" : ""}`} aria-hidden="true" />; }

export function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return <div role="status" className="toast"><i />{message}</div>;
}

export function Dialog({ title, open, onClose, children, footer, width }: { title: string; open: boolean; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="overlay" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className="dialog" style={width ? { width } : undefined} onClick={e => e.stopPropagation()}>
        <h2>{title}</h2>
        {children}
        {footer && <div className="foot">{footer}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ title, text, action, icon = "box" }: { title: ReactNode; text: ReactNode; action?: ReactNode; icon?: string }) {
  return (
    <div className="empty-state">
      <div className="icon"><Icon name={icon} size={20} /></div>
      <h2 style={{ fontSize: 18, fontWeight: 800, marginBottom: 6 }}>{title}</h2>
      <p className="muted" style={{ marginBottom: 16 }}>{text}</p>
      {action}
    </div>
  );
}

export function Skeleton({ h = 14, w = "100%", style }: { h?: number; w?: number | string; style?: CSSProperties }) {
  return <div className="skeleton" style={{ height: h, width: w, ...style }} aria-hidden="true" />;
}

export function ErrorNotice({ error, action }: { error: string; action?: ReactNode }) {
  return <div className="notice error"><div className="row" style={{ fontWeight: 700, color: "var(--orange)" }}><Dot color="var(--orange)" size={8} />Something went wrong</div><div className="mono xs" style={{ marginTop: 4, color: "var(--ink-2)", whiteSpace: "pre-wrap" }}>{error}</div>{action && <div style={{ marginTop: 6 }}>{action}</div>}</div>;
}

export function CheckDot({ ok, size = 16 }: { ok: boolean; size?: number }) {
  return <span style={{ width: size, height: size, borderRadius: "50%", background: ok ? "var(--blue)" : "var(--orange)", display: "inline-flex", alignItems: "center", justifyContent: "center", flex: "none" }}><Icon name={ok ? "check" : "warn"} size={10} stroke="#fff" width={2} /></span>;
}
