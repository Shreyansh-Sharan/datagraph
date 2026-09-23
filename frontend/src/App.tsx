import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConnectionsProvider } from "@polestar/connections";
import type { DatagraphApi } from "@/api";
import { AppProvider } from "@/state/app";
import { NotificationsProvider } from "@/state/notifications";
import { AppShell, DomainShell, PlainMain } from "@/layout/Shell";
import { Home } from "@/screens/Home";
import { Overview } from "@/screens/Overview";
import { Versions } from "@/screens/Versions";
import { Ask } from "@/screens/Ask";
import { Metadata } from "@/screens/Metadata";
import { Table } from "@/screens/Table";
import { Ontology } from "@/screens/Ontology";
import { Mapping } from "@/screens/Mapping";
import { Rules } from "@/screens/Rules";
import { Quality } from "@/screens/Quality";
import { Build } from "@/screens/Build";
import { Explore } from "@/screens/Explore";
import { Triples } from "@/screens/Triples";
import { Analytics } from "@/screens/Analytics";
import { Tasks } from "@/screens/Tasks";
import { Admin } from "@/screens/Admin";
import { NeedsVersion } from "@/screens/NeedsVersion";

import { CONNECTIONS_URL } from "@/config";

export function App({ api, connectionsUrl = CONNECTIONS_URL }: { api: DatagraphApi; connectionsUrl?: string }) {
  return (
    <AppProvider api={api}>
      <NotificationsProvider>
      <ConnectionsProvider baseUrl={connectionsUrl || "/hub"} headers={() => ({ "X-Actor": "alice" })}>
      <HashRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route element={<AppShell />}>
            <Route element={<PlainMain />}>
              <Route index element={<Home />} />
              <Route path="ask" element={<Ask />} />
              <Route path="tasks" element={<Tasks />} />
              <Route path="admin" element={<Admin />} />
            </Route>
            <Route path="d/:name" element={<DomainShell />}>
              <Route index element={<Overview />} />
              <Route path="overview" element={<Overview />} />
              <Route path="versions" element={<Versions />} />
              <Route path="ask" element={<Ask inDomain />} />
              <Route path="settings" element={<Overview defaultTab="connections" />} />
              <Route path="metadata" element={<NeedsVersion><Metadata /></NeedsVersion>} />
              <Route path="table" element={<NeedsVersion><Table /></NeedsVersion>} />
              <Route path="ontology" element={<NeedsVersion><Ontology /></NeedsVersion>} />
              <Route path="mapping" element={<NeedsVersion><Mapping /></NeedsVersion>} />
              <Route path="rules" element={<NeedsVersion><Rules /></NeedsVersion>} />
              <Route path="quality" element={<NeedsVersion><Quality /></NeedsVersion>} />
              <Route path="build" element={<NeedsVersion><Build /></NeedsVersion>} />
              <Route path="explore" element={<NeedsVersion><Explore /></NeedsVersion>} />
              <Route path="triples" element={<NeedsVersion><Triples /></NeedsVersion>} />
              <Route path="analytics" element={<NeedsVersion><Analytics /></NeedsVersion>} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </HashRouter>
      </ConnectionsProvider>
      </NotificationsProvider>
    </AppProvider>
  );
}
