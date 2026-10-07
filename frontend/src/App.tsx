import { lazy, Suspense } from "react";
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
import PurchaseSettings from "./pages/settings/PurchaseSettings";
import StageTemplates from "./pages/settings/StageTemplates";
import Tags from "./pages/settings/Tags";
import UnitsConversions from "./pages/settings/UnitsConversions";

const ex = () => import("./pages/execution/Pages");
const AttendanceToday = lazy(() => ex().then((m) => ({ default: m.AttendanceToday })));
const LabourMaster = lazy(() => ex().then((m) => ({ default: m.LabourMaster })));
const Subcontractors = lazy(() => ex().then((m) => ({ default: m.Subcontractors })));
const Assets = lazy(() => ex().then((m) => ({ default: m.Assets })));
const DailyReports = lazy(() => ex().then((m) => ({ default: m.DailyReports })));
const Checklists = lazy(() => ex().then((m) => ({ default: m.Checklists })));
// the material module is its own chunk
const Freight = lazy(() => import("./pages/material/Freight"));
const Grns = lazy(() => import("./pages/material/Grns"));
const Indents = lazy(() => import("./pages/material/Indents"));
const Pos = lazy(() => import("./pages/material/Pos"));
const NewPo = lazy(() => import("./pages/material/Pos").then((m) => ({ default: m.NewPo })));
const PoDetail = lazy(() => import("./pages/material/Pos").then((m) => ({ default: m.PoDetail })));
const Rfqs = lazy(() => import("./pages/material/Rfqs"));
const RfqDetail = lazy(() => import("./pages/material/Rfqs").then((m) => ({ default: m.RfqDetail })));
const Stores = lazy(() => import("./pages/material/Stores"));
const StoreDetail = lazy(() => import("./pages/material/Stores").then((m) => ({ default: m.StoreDetail })));
const Transfers = lazy(() => import("./pages/material/Stores").then((m) => ({ default: m.Transfers })));

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
  "/attendance": <AttendanceToday />,
  "/labour": <LabourMaster />,
  "/subcontractors": <Subcontractors />,
  "/assets": <Assets />,
  "/daily-reports": <DailyReports />,
  "/settings/checklists": <Checklists />,
  "/indents": <Indents />,
  "/rfqs": <Rfqs />,
  "/purchase-orders": <Pos />,
  "/grns": <Grns />,
  "/stores": <Stores />,
  "/transfers": <Transfers />,
  "/freight": <Freight />,
  "/settings/purchase": <PurchaseSettings />,
  "/admin/users": <Users />,
  "/admin/roles": <Roles />,
  "/admin/audit": <Audit />,
};

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<p className="muted">Loading…</p>}>
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
                <Route key={item.to} path={item.to} element={<RequirePermission perms={item.perms}>{PAGES[item.to] ?? <Placeholder title={item.label} />}</RequirePermission>} />
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
              {(
                [
                  ["/rfqs/:id", ["po.view"], <RfqDetail />],
                  ["/purchase-orders/new", ["po.edit"], <NewPo />],
                  ["/purchase-orders/:id", ["po.view"], <PoDetail />],
                  ["/stores/:id", ["store.view"], <StoreDetail />],
                ] as [string, string[], JSX.Element][]
              ).map(([path, perms, page]) => (
                <Route key={path} path={path} element={<RequirePermission perms={perms}>{page}</RequirePermission>} />
              ))}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </AuthProvider>
    </BrowserRouter>
  );
}
