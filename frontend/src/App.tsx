import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { RequireAuth, RequirePermission } from "./components/Guards";
import Layout from "./components/Layout";
import { MENU } from "./menu";
import Audit from "./pages/Audit";
import Clients from "./pages/Clients";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";
import Products from "./pages/Products";
import RateLibrary from "./pages/RateLibrary";
import Roles from "./pages/Roles";
import SystemDetail from "./pages/SystemDetail";
import Systems from "./pages/Systems";
import TcLibrary from "./pages/TcLibrary";
import Users from "./pages/Users";

const PAGES: Record<string, JSX.Element> = {
  "/clients": <Clients />,
  "/products": <Products />,
  "/systems": <Systems />,
  "/rate-library": <RateLibrary />,
  "/tc-library": <TcLibrary />,
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
            <Route
              path="/systems/:id"
              element={
                <RequirePermission perms={["library.view"]}>
                  <SystemDetail />
                </RequirePermission>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
