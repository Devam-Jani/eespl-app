import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

/** A client login holds only the client portal permissions. */
export function isClientLogin(permissions: Record<string, string>): boolean {
  const codes = Object.keys(permissions);
  return codes.length > 0 && codes.every((c) => c.startsWith("portal.") && c !== "portal.manage");
}

/** staff: the staff app; a client login is sent to the client portal instead. */
export function RequireAuth({ children, staff = false }: { children: ReactNode; staff?: boolean }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="center muted">Loading…</div>;
  if (!me) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (staff && isClientLogin(me.permissions)) return <Navigate to="/portal" replace />;
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
