import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Spinner } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import type { UserRole } from "@/types/models";

export function ProtectedRoute({
  roles,
  children,
}: {
  roles?: UserRole[];
  children?: ReactNode;
}): JSX.Element {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="grid min-h-screen place-items-center bg-ink-50 dark:bg-ink-950">
        <div className="flex flex-col items-center gap-3 text-ink-500 dark:text-ink-400">
          <Spinner className="h-6 w-6 text-brand-600" />
          <p className="text-sm">Restoring your session…</p>
        </div>
      </div>
    );
  }

  if (status !== "authenticated" || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (roles && !roles.includes(user.role)) {
    return <Navigate to={user.role === "resident" ? "/registry" : "/"} replace />;
  }

  return children ? <>{children}</> : <Outlet />;
}
