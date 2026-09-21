import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { Button, EmptyState } from "@/components/ui";
import { useApp } from "@/state/app";
import { useDomain } from "@/state/domain";

/** Design tabs need a version; without one, show the create-a-draft empty state instead. */
export function NeedsVersion({ children }: { children: ReactNode }) {
  const { domain, version, patch } = useDomain();
  const { api, config, say, can } = useApp();
  const screen = useLocation().pathname.split("/")[3] ?? "";
  if (version) return <>{children}</>;
  const label = screen ? screen[0].toUpperCase() + screen.slice(1) : "This tab";
  const source = config.sourceKind === "databricks" ? "Databricks" : "Postgres";
  return (
    <EmptyState title={`${domain.name} has no version yet`} text={`${label} needs a version to work on. Create a draft, then import tables from ${source} and draft the ontology.`}
      action={can("builder") ? <Button variant="primary" onClick={async () => { patch(await api.createDraft(domain.name)); say("Draft v1 created"); }}>Create a draft version</Button> : undefined} />
  );
}
