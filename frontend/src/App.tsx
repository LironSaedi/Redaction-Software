import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import * as api from "./api";
import { SetupWizard } from "./pages/setup/SetupWizard";
import { FullScreen } from "./components/AppScreens";
import { AuthProvider, hasRole, useAuth } from "./auth";
import { ToastProvider } from "./components/Toast";
import { TooltipLayer } from "./components/Tooltip";
import { MetaProvider } from "./meta";
import { JobsProvider } from "./jobs";
import { Layout } from "./components/Layout";
import { Loading, EmptyState } from "./components/ui";
import { LoginPage } from "./pages/LoginPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { CasesPage } from "./pages/CasesPage";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { ReviewPage } from "./pages/review/ReviewPage";
import { ExportViewerPage } from "./pages/ExportViewerPage";
import { LibraryPage } from "./pages/library/LibraryPage";
import { AuditPage } from "./pages/AuditPage";
import { UsersPage } from "./pages/admin/UsersPage";
import { WatchersPage } from "./pages/admin/WatchersPage";
import { SystemPage } from "./pages/admin/SystemPage";
import type { Role, SetupState } from "./types";

function RequireAuth({ children, allowPasswordChange = false }: { children: ReactNode; allowPasswordChange?: boolean }) {
  const { status, user } = useAuth();
  const location = useLocation();
  if (status === "loading") return <Loading label="Opening Obscura…" />;
  if (status !== "authenticated" || !user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.must_change_password && !allowPasswordChange) return <Navigate to="/change-password" replace />;
  return <>{children}</>;
}

function RequireRole({ role, children }: { role: Role; children: ReactNode }) {
  const { user } = useAuth();
  if (!hasRole(user, role)) {
    return (
      <div className="page">
        <EmptyState title="Not available for your role">
          This area needs the <strong>{role}</strong> role or higher.
        </EmptyState>
      </div>
    );
  }
  return <>{children}</>;
}

function PasswordRoute() {
  const { user } = useAuth();
  // forced change: full-screen; voluntary change: inside the shell
  if (user?.must_change_password) return <ChangePasswordPage />;
  return <Navigate to="/account/password" replace />;
}

function NotFound() {
  return (
    <div className="page">
      <EmptyState title="Page not found">The link may be out of date.</EmptyState>
    </div>
  );
}

/**
 * First-run setup of an installed copy comes before everything else (even before the automatic local sign-in):
 * GET /api/setup/state → needed shows the wizard full-screen at /setup.
 */
export function SetupGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SetupState | "remote" | null>(null);
  useEffect(() => {
    let alive = true;
    api.getSetupState().then(
      (s) => alive && setState(s),
      (e: unknown) => {
        if (!alive) return;
        // 403: setup is open but this browser is on another computer; anything else: carry on normally
        setState(e instanceof api.ApiError && e.status === 403 ? "remote" : { needed: false });
      },
    );
    return () => {
      alive = false;
    };
  }, []);
  if (state === null) return <Loading label="Opening Obscura…" />;
  if (state === "remote")
    return (
      <FullScreen>
        <h1 className="screen-title">Obscura is not set up yet</h1>
        <p className="muted center">Finish the first-run setup on the computer where Obscura is installed, then open this page again.</p>
      </FullScreen>
    );
  if (state.needed)
    return (
      <Routes>
        <Route path="/setup" element={<SetupWizard state={state} />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    );
  return <>{children}</>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/setup" element={<Navigate to="/" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/change-password"
        element={
          <RequireAuth allowPasswordChange>
            <PasswordRoute />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <MetaProvider>
              <Layout />
            </MetaProvider>
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        <Route path="/cases/:caseId/:tab" element={<CaseDetailPage />} />
        <Route path="/files/:fileId" element={<ReviewPage />} />
        <Route path="/exports/:exportId" element={<ExportViewerPage />} />
        <Route path="/account/password" element={<ChangePasswordPage />} />
        <Route path="/library" element={<Navigate to="/library/lists" replace />} />
        <Route
          path="/library/:tab"
          element={
            <RequireRole role="redactor">
              <LibraryPage />
            </RequireRole>
          }
        />
        <Route
          path="/audit"
          element={
            <RequireRole role="supervisor">
              <AuditPage />
            </RequireRole>
          }
        />
        <Route path="/admin" element={<Navigate to="/admin/users" replace />} />
        <Route
          path="/admin/users"
          element={
            <RequireRole role="admin">
              <UsersPage />
            </RequireRole>
          }
        />
        <Route
          path="/admin/watchers"
          element={
            <RequireRole role="admin">
              <WatchersPage />
            </RequireRole>
          }
        />
        <Route
          path="/admin/system"
          element={
            <RequireRole role="admin">
              <SystemPage />
            </RequireRole>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <SetupGate>
          <AuthProvider>
            <JobsProvider>
              <AppRoutes />
            </JobsProvider>
          </AuthProvider>
        </SetupGate>
        <TooltipLayer />
      </ToastProvider>
    </BrowserRouter>
  );
}
