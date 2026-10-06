import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { RequireAuth, RequirePermission } from "./components/Guards";
import Layout from "./components/Layout";
import { MENU } from "./menu";
import Audit from "./pages/Audit";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";
import Roles from "./pages/Roles";
import Users from "./pages/Users";

const PAGES: Record<string, JSX.Element> = {
  "/admin/users": <Users />,
  "/admin/roles": <Roles />,
  "/admin/audit": <Audit />,
};

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route index element={<Home />} />
            {MENU.map((item) => (
              <Route
                key={item.to}
                path={item.to}
                element={
                  <RequirePermission perms={item.perms}>
                    {PAGES[item.to] ?? <Placeholder title={item.label} />}
                  </RequirePermission>
                }
              />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
