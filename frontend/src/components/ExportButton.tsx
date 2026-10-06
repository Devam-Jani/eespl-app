import { useState } from "react";
import { downloadFile } from "../api";
import { errorText } from "../format";

/** "Export Excel" for a list page. `path` is the list's /export endpoint with the same filters;
 * the server applies the same permission and field hiding as the list. */
export default function ExportButton({ path, label = "Export Excel" }: { path: string; label?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="btn"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await downloadFile(path);
        } catch (err) {
          alert(`Export failed: ${errorText(err)}`);
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? "Exporting…" : `⤓ ${label}`}
    </button>
  );
}
