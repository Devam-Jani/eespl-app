import { useState } from "react";
import { api } from "../api";
import { errorText } from "../format";
import { Button, Field } from "../ui/components";

/** "Done" on an action item: doing the action in the app closes it by itself, so closing it by
 * hand asks why the action itself was not done (shown on the site's process timeline). */
export function DoneButton({ id, action, onDone }: { id: number; action: string | null; onDone: () => void }) {
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  async function save() {
    try {
      await api(`/api/process/notifications/${id}/done`, { method: "POST", json: { reason } });
      setAsking(false);
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }
  if (!asking)
    return (
      <Button size="small" onClick={() => setAsking(true)}>
        Done
      </Button>
    );
  return (
    <span className="done-reason">
      <Field label="Reason" bare>
        <input
          autoFocus
          value={reason}
          maxLength={300}
          placeholder={`Why was "${action ?? "the action"}" not done in the app?`}
          onChange={(e) => setReason(e.target.value)}
          aria-label="Reason"
        />
      </Field>
      <Button variant="primary" size="small" disabled={reason.trim().length < 3} onClick={() => void save()}>
        Close it
      </Button>
      <Button variant="ghost" size="small" onClick={() => setAsking(false)}>
        Cancel
      </Button>
      {error && <span className="small text-danger">{error}</span>}
    </span>
  );
}
