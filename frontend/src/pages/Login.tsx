import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import type { TwoStep } from "../auth";
import { useAuth } from "../auth";
import { errorText } from "../format";
import { TrainingBanner, useMode } from "../ops/Pages";

export default function Login() {
  const mode = useMode();
  const { me, login, finishTwoStep } = useAuth();
  const [step, setStep] = useState<TwoStep | null>(null);
  const [code, setCode] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (me) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (step) {
        await finishTwoStep(step.ticket, code);
        navigate(from, { replace: true });
        return;
      }
      const next = await login(email, password);
      if (next) {
        setStep(next);
        return;
      }
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? errorText(err) : "Could not reach the server");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <TrainingBanner mode={mode} />
      <form className="login-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="login-brand">
          <span className="app-mark" aria-hidden="true">
            E
          </span>
          <div>
            <b>EESPL</b>
            <small>Waterproofing ERP</small>
          </div>
        </div>
        <h1 id="login-title">Sign in</h1>
        <p className="muted login-lead">{mode?.training ? "The training company: practise freely, nothing here is real." : "Your sites, bills and approvals in one place."}</p>
        {error && <div className="alert alert-error">{error}</div>}
        {step ? (
          <div className="two-step">
            {step.two_step === "enroll" ? (
              <>
                <p>
                  <b>Set up two-step sign-in.</b> Your role needs it: scan this
                  code with an authenticator app (Google or Microsoft
                  Authenticator), then type the 6-digit code it shows.
                </p>
                {step.qr && (
                  <img
                    className="qr"
                    alt="QR code for the authenticator app"
                    src={`data:image/svg+xml;base64,${btoa(step.qr)}`}
                  />
                )}
                <p className="small muted">
                  Or type this key into the app:{" "}
                  <code className="secret">{step.secret}</code>
                </p>
              </>
            ) : (
              <p>Type the 6-digit code from your authenticator app.</p>
            )}
            <label className="field">
              <span>Code</span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9 ]{6,8}"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoFocus
              />
            </label>
            <button className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "Checking…" : "Sign in"}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-block"
              onClick={() => (setStep(null), setCode(""), setPassword(""))}
            >
              Start again
            </button>
          </div>
        ) : (
          <>
            <label className="field">
              <span>Email</span>
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </label>
            <label className="field">
              <span>Password</span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </label>
            <button className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
