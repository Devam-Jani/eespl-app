import { useEffect, useState } from "react";

type Health = { status: string; db: string; detail?: string };

type State =
  | { kind: "loading" }
  | { kind: "done"; httpStatus: number; body: Health }
  | { kind: "error"; message: string };

export default function App() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    fetch("/api/health")
      .then(async (res) => setState({ kind: "done", httpStatus: res.status, body: await res.json() }))
      .catch((err: unknown) => setState({ kind: "error", message: String(err) }));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>EESPL App</h1>
      <h2>API health</h2>
      {state.kind === "loading" && <p>Checking…</p>}
      {state.kind === "error" && <p style={{ color: "crimson" }}>Request failed: {state.message}</p>}
      {state.kind === "done" && (
        <>
          <p>
            HTTP {state.httpStatus} · status: <strong>{state.body.status}</strong> · db:{" "}
            <strong>{state.body.db}</strong>
          </p>
          <pre>{JSON.stringify(state.body, null, 2)}</pre>
        </>
      )}
    </main>
  );
}
