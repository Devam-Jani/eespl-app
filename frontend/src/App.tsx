import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { RequireAuth, RequirePermission } from "./components/Guards";
import Layout from "./components/Layout";
import { MENU } from "./menu";
import Audit from "./pages/Audit";
import Channels from "./pages/Channels";
import Clients from "./pages/Clients";
import Home from "./pages/Home";
import LeadDetail from "./pages/LeadDetail";
import Leads from "./pages/Leads";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";
import Products from "./pages/Products";
import RateLibrary from "./pages/RateLibrary";
import Roles from "./pages/Roles";
import SiteDetail from "./pages/SiteDetail";
import Sites from "./pages/Sites";
import SystemDetail from "./pages/SystemDetail";
import Systems from "./pages/Systems";
import TcLibrary from "./pages/TcLibrary";
import TenderDetail from "./pages/TenderDetail";
import Tenders from "./pages/Tenders";
import Users from "./pages/Users";
import Vendors from "./pages/Vendors";
import Categories from "./pages/settings/Categories";
import CompanyBanks from "./pages/settings/CompanyBanks";
import CompanyProfile from "./pages/settings/CompanyProfile";
import GstinAddresses from "./pages/settings/GstinAddresses";
import KylasSettingsPage from "./pages/settings/KylasSettings";
import StageTemplates from "./pages/settings/StageTemplates";
import Tags from "./pages/settings/Tags";
import UnitsConversions from "./pages/settings/UnitsConversions";

const PAGES: Record<string, JSX.Element> = {
  "/clients": <Clients />,
  "/channels": <Channels />,
  "/products": <Products />,
  "/systems": <Systems />,
  "/rate-library": <RateLibrary />,
  "/tc-library": <TcLibrary />,
  "/vendors": <Vendors />,
  "/tenders": <Tenders />,
  "/leads": <Leads />,
  "/settings/kylas": <KylasSettingsPage />,
  "/sites": <Sites />,
  "/settings/stage-templates": <StageTemplates />,
  "/settings/company": <CompanyProfile />,
  "/settings/gstins": <GstinAddresses />,
  "/settings/bank-accounts": <CompanyBanks />,
  "/settings/categories": <Categories />,
  "/settings/tags": <Tags />,
  "/settings/units": <UnitsConversions />,
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
            <Route
              path="/tenders/:id"
              element={
                <RequirePermission perms={["tender.view"]}>
                  <TenderDetail />
                </RequirePermission>
              }
            />
            <Route
              path="/sites/:id"
              element={
                <RequirePermission perms={["site.view"]}>
                  <SiteDetail />
                </RequirePermission>
              }
            />
            <Route
              path="/leads/:id"
              element={
                <RequirePermission perms={["leads.view"]}>
                  <LeadDetail />
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
