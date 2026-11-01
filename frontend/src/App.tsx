import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AccessLogsPage } from "@/pages/AccessLogs";
import { DashboardPage } from "@/pages/Dashboard";
import { LiveMonitorPage } from "@/pages/LiveMonitor";
import { LoginPage } from "@/pages/Login";
import { NotFoundPage } from "@/pages/NotFound";
import { RegistryPage } from "@/pages/Registry";
import { SecurityPage } from "@/pages/Security";
import { SettingsPage } from "@/pages/Settings";
import { VisitorsPage } from "@/pages/Visitors";

export default function App(): JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route
            index
            element={
              <ProtectedRoute roles={["admin", "security_officer"]}>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="live"
            element={
              <ProtectedRoute roles={["admin", "security_officer"]}>
                <LiveMonitorPage />
              </ProtectedRoute>
            }
          />
          <Route path="registry" element={<RegistryPage />} />
          <Route path="visitors" element={<VisitorsPage />} />
          <Route path="logs" element={<AccessLogsPage />} />
          <Route
            path="security"
            element={
              <ProtectedRoute roles={["admin", "security_officer"]}>
                <SecurityPage />
              </ProtectedRoute>
            }
          />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="404" element={<NotFoundPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>

      <Route path="/home" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
