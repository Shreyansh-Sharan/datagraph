// Notifications: every activity across the domains, kept in one place and polled from the server.
// Running builds and jobs update in place; when one finishes, the result is announced on whatever
// screen the user is on, so nothing that happened in the background is missed.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useApp } from "./app";
import type { Notification } from "@/api";

interface NotificationsState {
  items: Notification[];          // newest first
  unread: number;
  running: number;
  markRead: (ids?: number[], until?: number) => Promise<void>;
  refresh: () => Promise<void>;
  stale: boolean;                 // the last poll failed: the bell shows it
}

const Ctx = createContext<NotificationsState | null>(null);
const EVERY = 5000, WHILE_RUNNING = 2000;

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { api, say } = useApp();
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [stale, setStale] = useState(false);
  const latest = useRef<number | null>(null);
  const known = useRef<Map<number, Notification>>(new Map());

  const merge = useCallback((incoming: Notification[]) => {
    for (const n of incoming) {
      const was = known.current.get(n.id);
      if (was && was.status === "running" && n.status !== "running") say(n.title);   // a build or job finished while the user was elsewhere
      known.current.set(n.id, n);
    }
    setItems([...known.current.values()].sort((a, b) => b.id - a.id).slice(0, 100));
  }, [say]);

  const refresh = useCallback(async () => {
    try {
      const feed = await api.notifications(latest.current ?? undefined);
      merge(feed.items); setUnread(feed.unread); latest.current = feed.latest_id; setStale(false);
    } catch { setStale(true); }
  }, [api, merge]);

  const running = items.filter(n => n.status === "running").length;
  useEffect(() => {
    let alive = true, timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      if (!alive) return;
      if (typeof document === "undefined" || document.visibilityState === "visible") await refresh();
      if (alive) timer = setTimeout(tick, known.current.size && [...known.current.values()].some(n => n.status === "running") ? WHILE_RUNNING : EVERY);
    };
    void tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [refresh]);

  const markRead = useCallback(async (ids?: number[], until?: number) => {
    const r = await api.markRead({ ids, until });
    setUnread(r.unread);
    for (const n of known.current.values()) if ((ids && ids.includes(n.id)) || (until != null && n.id <= until)) known.current.set(n.id, { ...n, read: true });
    setItems([...known.current.values()].sort((a, b) => b.id - a.id).slice(0, 100));
  }, [api]);

  const value = useMemo<NotificationsState>(() => ({ items, unread, running, markRead, refresh, stale }), [items, unread, running, markRead, refresh, stale]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNotifications(): NotificationsState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useNotifications outside NotificationsProvider");
  return v;
}
