// Presentation helpers shared by the adapters: relative times and audit sentences.

/** "just now", "5 min ago", "2 h ago", "3 d ago", or the date beyond a month; "in 12 min" for the future. */
export function relTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = now - t, future = diff < 0, s = Math.abs(diff) / 1000;
  const wrap = (x: string) => (future ? `in ${x}` : `${x} ago`);
  if (s < 45) return future ? "in under a minute" : "just now";
  if (s < 3600) return wrap(`${Math.round(s / 60)} min`);
  if (s < 86400) return wrap(`${Math.round(s / 3600)} h`);
  if (s < 30 * 86400) return wrap(`${Math.round(s / 86400)} d`);
  return new Date(iso).toLocaleDateString();
}

/** Backend audit action -> the verb phrase the log shows between the actor and "vN". */
export function humanAction(action: string, detail: Record<string, unknown> | null | undefined): string {
  const d = detail ?? {};
  switch (action) {
    case "version.created": return "created draft";
    case "version.imported": return "imported";
    case "version.deleted": return "deleted draft";
    case "content.updated": return Array.isArray(d.changed) && d.changed.length ? `updated ${(d.changed as string[]).map(c => c.replace("_ttl", "")).join(", ")} of` : "updated";
    case "lease.acquired": return d.forced ? "force-took the lease on" : "took the lease on";
    case "lease.released": return "released the lease on";
    case "status.in_review": return "submitted for review";
    case "status.draft": return "sent back to draft";
    case "status.published": return "published";
    case "status.archived": return "archived";
    case "review.added": return d.approved ? "approved" : "rejected";
    case "build.started": return "started a build of";
    case "build.succeeded": return "built";
    case "build.failed": return "build failed for";
    case "build.cancelled": return "cancelled a build of";
    case "version.activated": return "set active version";
    case "version.deactivated": return "cleared the active version of";
    case "comment.added": return "commented on";
    case "domain.updated": return "updated the settings of";
    case "mcp_policy.updated": return "changed the MCP policy of";
    default: return action.replace(/[._]/g, " ");
  }
}
