import { useState } from "react";
import { downloadFile } from "../api";
import { showError } from "../format";
import { Button } from "../ui/components";

/** "Export Excel" for a list page. `path` is the list's /export endpoint with the same filters;
 * the server applies the same permission and field hiding as the list. */
export default function ExportButton({ path, label = "Export Excel" }: { path: string; label?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await downloadFile(path);
        } catch (err) {
          showError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? "Exporting…" : `⤓ ${label}`}
    </Button>
  );
}
