// Where the user is: the assistant sends it with every question so "this table" resolves.
import { useLocation, useParams, useSearchParams } from "react-router-dom";
import type { AssistantContext } from "@/api";

export function useAssistantContext(): AssistantContext {
  const { name } = useParams();
  const [sp] = useSearchParams();
  const { pathname } = useLocation();
  const screen = name ? (pathname.split("/").filter(Boolean)[2] ?? "overview") : undefined;
  const schema = sp.get("schema"), table = sp.get("table");
  const v = sp.get("v");
  return {
    ...(name ? { domain: name } : {}), ...(v ? { version: Number(v) } : {}), ...(screen ? { screen } : {}),
    ...(table ? { table: schema ? `${schema}.${table}` : table } : {}), ...(sp.get("cls") ? { cls: sp.get("cls")! } : {}), ...(sp.get("entity") ? { entity: sp.get("entity")! } : {}),
  };
}
