import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import type { TwoStep } from "../auth";
import { useAuth } from "../auth";
import { useBranding } from "../branding";
import { errorText } from "../format";
import { TrainingBanner, useMode } from "../ops/Pages";
import { Button, Field } from "../ui/components";

export default function Login() {
  const mode = useMode();
  const brand = useBranding();
  const { me, login, finishTwoStep } = useAuth();
  const [step, setStep] = useState<TwoStep | null>(null);
  const [code, setCode] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const [forgot, setForgot] = useState(() => new URLSearchParams(location.search).has("forgot"));
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

  if (forgot) {
    return (
      <div className="login-page">
        <TrainingBanner mode={mode} />
        <ForgotPassword email={email} onBack={() => setForgot(false)} />
        {brand?.company_line && <p className="login-foot">{brand.company_line}</p>}
      </div>
    );
  }

  return (
    <div className="login-page">
      <TrainingBanner mode={mode} />
      <form className="login-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="login-brand">
          <span className="app-mark" aria-hidden="true">
            {brand?.product_name.slice(0, 1)}
          </span>
          <div>
            <b>{brand?.product_name}</b>
            <small>{brand?.product_tag}</small>
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
            <Field label="Code">
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9 ]{6,8}"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoFocus
              />
            </Field>
            <Button type="submit" variant="primary" block disabled={busy}>
              {busy ? "Checking…" : "Sign in"}
            </Button>
            <Button
              type="button"
              variant="ghost" block
              onClick={() => (setStep(null), setCode(""), setPassword(""))}
            >
              Start again
            </Button>
          </div>
        ) : (
          <>
            <Field label="Email">
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </Field>
            <Field label="Password">
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            <Button type="submit" variant="primary" block disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
            <Button type="button" variant="ghost" block onClick={() => setForgot(true)}>
              Forgot password?
            </Button>
          </>
        )}
      </form>
      {brand?.company_line && <p className="login-foot">{brand.company_line}</p>}
    </div>
  );
}

/** "Forgot password": the same answer for every email (it never says whether a login exists). */
function ForgotPassword({ email: start, onBack }: { email: string; onBack: () => void }) {
  const [email, setEmail] = useState(start);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ message: string }>("/api/auth/forgot-password", { method: "POST", json: { email } });
      setDone(r.message);
    } catch (err) {
      setError(err instanceof ApiError ? errorText(err) : "Could not reach the server");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="login-card" onSubmit={(e) => void send(e)} aria-labelledby="forgot-title">
      <h1 id="forgot-title">Forgot password</h1>
      <p className="muted login-lead">Type the email address you sign in with. We email you a link to set a new password.</p>
      {error && <div className="alert alert-error">{error}</div>}
      {done ? (
        <div className="alert alert-ok">{done} Check the spam folder too.</div>
      ) : (
        <>
          <Field label="Email">
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </Field>
          <Button type="submit" variant="primary" block disabled={busy}>
            {busy ? "Sending…" : "Email me a link"}
          </Button>
        </>
      )}
      <Button type="button" variant="ghost" block onClick={onBack}>
        Back to sign in
      </Button>
    </form>
  );
}
