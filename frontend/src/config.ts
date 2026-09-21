/** Where the connection module (mf-studio-connectors hub) is reached from the browser.
 *  Empty means it is not configured: the Configure screen then shows the domain's pickers only. */
export const CONNECTIONS_URL: string = ((import.meta.env.VITE_CONNECTIONS_URL as string | undefined) ?? "").trim();
