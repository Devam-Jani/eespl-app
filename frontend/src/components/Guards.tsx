import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="center muted">Loading…</div>;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

export function RequirePermission({ perms, children }: { perms: string[]; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(...perms)) {
    return (
      <div className="card">
        <h1>No access</h1>
        <p className="muted">You do not have permission to open this page.</p>
      </div>
    );
  }
  return <>{children}</>;
}
