import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { RequireAuth, RequirePermission } from "./components/Guards";
import Layout from "./components/Layout";
import { MENU } from "./menu";
import Audit from "./pages/Audit";
import Channels from "./pages/Channels";
import Clients from "./pages/Clients";
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

// the client portal is its own chunk (and its own phone-first layout)
const portal = () => import("./portal/Portal");
const PortalLayout = lazy(() => portal().then((m) => ({ default: m.PortalLayout })));
const PortalHome = lazy(() => portal().then((m) => ({ default: m.PortalHome })));
const PortalSitePage = lazy(() => portal().then((m) => ({ default: m.PortalSitePage })));
const InviteAccept = lazy(() => portal().then((m) => ({ default: m.InviteAccept })));
const Snags = lazy(() => import("./pages/Snags"));
// dashboards and analytics (with their charts) are one chunk
const Dashboard = lazy(() => import("./analytics/Dashboard"));
const an = () => import("./analytics/Pages");
const SitesAnalytics = lazy(() => an().then((m) => ({ default: m.SitesAnalytics })));
const FinanceAnalytics = lazy(() => an().then((m) => ({ default: m.FinanceAnalytics })));
const ProfitabilityAnalytics = lazy(() => an().then((m) => ({ default: m.ProfitabilityAnalytics })));
const PurchaseAnalytics = lazy(() => an().then((m) => ({ default: m.PurchaseAnalytics })));
const LabourAnalytics = lazy(() => an().then((m) => ({ default: m.LabourAnalytics })));
const StrategyAnalytics = lazy(() => an().then((m) => ({ default: m.StrategyAnalytics })));
const DrillPage = lazy(() => an().then((m) => ({ default: m.DrillPage })));
const AlertsPage = lazy(() => an().then((m) => ({ default: m.AlertsPage })));
const ReportsPage = lazy(() => an().then((m) => ({ default: m.ReportsPage })));
const fin = () => import("./pages/finance/Reports");
const Billing = lazy(() => import("./pages/finance/Billing"));
const Payables = lazy(() => import("./pages/finance/Payables"));
const PettyCash = lazy(() => import("./pages/finance/PettyCash"));
const Payroll = lazy(() => import("./pages/finance/Payroll"));
const SiteProfit = lazy(() => import("./pages/finance/Reports"));
const Tally = lazy(() => fin().then((m) => ({ default: m.Tally })));
const FinanceSettings = lazy(() => fin().then((m) => ({ default: m.FinanceSettings })));
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
  "/snags": <Snags />,
  "/dashboard": <Dashboard />,
  "/analytics/sites": <SitesAnalytics />,
  "/analytics/finance": <FinanceAnalytics />,
  "/analytics/profitability": <ProfitabilityAnalytics />,
  "/analytics/purchase": <PurchaseAnalytics />,
  "/analytics/labour": <LabourAnalytics />,
  "/analytics/strategy": <StrategyAnalytics />,
  "/alerts": <AlertsPage />,
  "/reports": <ReportsPage />,
  "/settings/stage-templates": <StageTemplates />,
  "/settings/company": <CompanyProfile />,
  "/settings/gstins": <GstinAddresses />,
  "/settings/bank-accounts": <CompanyBanks />,
  "/settings/categories": <Categories />,
  "/settings/tags": <Tags />,
  "/settings/units": <UnitsConversions />,
  "/billing": <Billing />,
  "/payables": <Payables />,
  "/petty-cash": <PettyCash />,
  "/payroll": <Payroll />,
  "/site-profit": <SiteProfit />,
  "/tally": <Tally />,
  "/settings/finance": <FinanceSettings />,
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
            <Route path="/portal/invite/:token" element={<InviteAccept />} />
            <Route
              path="/portal"
              element={
                <RequireAuth>
                  <PortalLayout />
                </RequireAuth>
              }
            >
              <Route index element={<PortalHome />} />
              <Route path="sites/:id" element={<PortalSitePage />} />
              <Route path="*" element={<Navigate to="/portal" replace />} />
            </Route>
            <Route
              element={
                <RequireAuth staff>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="/drill" element={<DrillPage />} />
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
