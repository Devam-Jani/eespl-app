import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { RequireAuth, RequirePermission } from "./components/Guards";
import Layout from "./components/Layout";
import { MENU } from "./menu";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";
import { HelperCard } from "./helper/Helper";
// every page in its own chunk: the first load carries the shell, the sign-in and the menu only
const Audit = lazy(() => import("./pages/Audit"));
const Channels = lazy(() => import("./pages/Channels"));
const Clients = lazy(() => import("./pages/Clients"));
const LeadDetail = lazy(() => import("./pages/LeadDetail"));
const Leads = lazy(() => import("./pages/Leads"));
const Products = lazy(() => import("./pages/Products"));
const RateLibrary = lazy(() => import("./pages/RateLibrary"));
const Roles = lazy(() => import("./pages/Roles"));
const SiteDetail = lazy(() => import("./pages/SiteDetail"));
const Sites = lazy(() => import("./pages/Sites"));
const SystemDetail = lazy(() => import("./pages/SystemDetail"));
const Systems = lazy(() => import("./pages/Systems"));
const TcLibrary = lazy(() => import("./pages/TcLibrary"));
const TenderDetail = lazy(() => import("./pages/TenderDetail"));
const Tenders = lazy(() => import("./pages/Tenders"));
const Users = lazy(() => import("./pages/Users"));
const Vendors = lazy(() => import("./pages/Vendors"));
const Categories = lazy(() => import("./pages/settings/Categories"));
const CompanyBanks = lazy(() => import("./pages/settings/CompanyBanks"));
const CompanyProfile = lazy(() => import("./pages/settings/CompanyProfile"));
const GstinAddresses = lazy(() => import("./pages/settings/GstinAddresses"));
const KylasSettingsPage = lazy(() => import("./pages/settings/KylasSettings"));
const PurchaseSettings = lazy(() => import("./pages/settings/PurchaseSettings"));
const StageTemplates = lazy(() => import("./pages/settings/StageTemplates"));
const Tags = lazy(() => import("./pages/settings/Tags"));
const UnitsConversions = lazy(() => import("./pages/settings/UnitsConversions"));

// the client portal is its own chunk (and its own phone-first layout)
const portal = () => import("./portal/Portal");
const PortalLayout = lazy(() => portal().then((m) => ({ default: m.PortalLayout })));
const PortalHome = lazy(() => portal().then((m) => ({ default: m.PortalHome })));
const PortalSitePage = lazy(() => portal().then((m) => ({ default: m.PortalSitePage })));
const helperPages = () => import("./helper/Pages");
const IssueLog = lazy(() => helperPages().then((m) => ({ default: m.IssueLog })));
const IssuePage = lazy(() => helperPages().then((m) => ({ default: m.IssuePage })));
const MyReports = lazy(() => helperPages().then((m) => ({ default: m.MyReports })));
const InviteAccept = lazy(() => portal().then((m) => ({ default: m.InviteAccept })));
const Snags = lazy(() => import("./pages/Snags"));
// site survey (with its measuring camera) is its own chunk
const sv = () => import("./survey/SurveyPages");
const SurveysList = lazy(() => sv().then((m) => ({ default: m.SurveysList })));
const SurveyDetail = lazy(() => sv().then((m) => ({ default: m.SurveyDetail })));
const PilotReport = lazy(() => sv().then((m) => ({ default: m.PilotReport })));
const SurveySettings = lazy(() => sv().then((m) => ({ default: m.SurveySettings })));
// quotations (editor and library) are their own chunk
const qp = () => import("./quotations/QuotationPages");
const QuotationsList = lazy(() => qp().then((m) => ({ default: m.QuotationsList })));
const QuotationEditor = lazy(() => qp().then((m) => ({ default: m.QuotationEditor })));
const ReceiptPage = lazy(() => import("./receipt/ReceiptPage"));
// rate working, the master price list and labour rates (the director's review, 12 Oct)
const cp = () => import("./costing/Pages");
const QuotationWorking = lazy(() => cp().then((m) => ({ default: m.QuotationWorking })));
const ProductPrices = lazy(() => cp().then((m) => ({ default: m.ProductPrices })));
const LabourRates = lazy(() => cp().then((m) => ({ default: m.LabourRates })));
// AutoCAD takeoff: the drawing viewer and the areas (its own chunk)
const TakeoffPage = lazy(() => import("./takeoff/Pages").then((m) => ({ default: m.TakeoffPage })));
// the X-ray 3D building model from the drawing (its own chunk)
const BuildingBuilder = lazy(() => import("./xray/Builder"));
const sc = () => import("./sitecontrol/Pages");
const Deliveries = lazy(() => sc().then((m) => ({ default: m.Deliveries })));
const DeliveryDetail = lazy(() => sc().then((m) => ({ default: m.DeliveryDetail })));
const RateContracts = lazy(() => sc().then((m) => ({ default: m.RateContracts })));
const ReadyToBill = lazy(() => sc().then((m) => ({ default: m.ReadyToBill })));
const NewAreas = lazy(() => sc().then((m) => ({ default: m.NewAreas })));
const NewAreaForm = lazy(() => sc().then((m) => ({ default: m.NewAreaForm })));
const Productivity = lazy(() => sc().then((m) => ({ default: m.Productivity })));
const Consumption = lazy(() => sc().then((m) => ({ default: m.Consumption })));
const SiteControlSettings = lazy(() => sc().then((m) => ({ default: m.SiteControlSettings })));
const WorkFronts = lazy(() => import("./pages/site/WorkFronts"));
const pr = () => import("./process/Pages");
const Notifications = lazy(() => pr().then((m) => ({ default: m.Notifications })));
const Escalated = lazy(() => pr().then((m) => ({ default: m.Escalated })));
const ProcessRules = lazy(() => pr().then((m) => ({ default: m.ProcessRules })));
const MyNotificationSettings = lazy(() => pr().then((m) => ({ default: m.MyNotificationSettings })));
const fd = () => import("./field/MyDay");
const MyDay = lazy(() => fd().then((m) => ({ default: m.MyDay })));
const fm = () => import("./field/Maps");
const DayMap = lazy(() => fm().then((m) => ({ default: m.DayMap })));
const TeamMap = lazy(() => fm().then((m) => ({ default: m.TeamMap })));
const fc = () => import("./field/Claims");
const Claims = lazy(() => fc().then((m) => ({ default: m.Claims })));
const ClaimDetail = lazy(() => fc().then((m) => ({ default: m.ClaimDetail })));
const fa = () => import("./field/Admin");
const GangCheckIn = lazy(() => fa().then((m) => ({ default: m.GangCheckIn })));
const FieldSettings = lazy(() => fa().then((m) => ({ default: m.FieldSettings })));
const md = () => import("./methodology/Pages");
const MethodologyHome = lazy(() => md().then((m) => ({ default: m.MethodologyHome })));
const MethodSystemPage = lazy(() => md().then((m) => ({ default: m.SystemPage })));
const StandardPage = lazy(() => md().then((m) => ({ default: m.StandardPage })));
const MethodologyPage = lazy(() => md().then((m) => ({ default: m.MethodologyPage })));
const SiteMethodology = lazy(() => md().then((m) => ({ default: m.SiteMethodology })));
// work orders, client approvals, bill steps, payments, completion and issues (the 16 Oct review)
const co = () => import("./closeout/Pages");
const WorkOrders = lazy(() => co().then((m) => ({ default: m.WorkOrders })));
const WorkOrderPage = lazy(() => co().then((m) => ({ default: m.WorkOrderPage })));
const SiteZones = lazy(() => co().then((m) => ({ default: m.SiteZones })));
const BillingChecklist = lazy(() => co().then((m) => ({ default: m.BillingChecklist })));
// go-live: the account, set password, security, backups, user import, roles report, help
const ops = () => import("./ops/Pages");
const SetPassword = lazy(() => ops().then((m) => ({ default: m.SetPassword })));
const Account = lazy(() => ops().then((m) => ({ default: m.Account })));
const SecuritySettings = lazy(() => ops().then((m) => ({ default: m.SecuritySettings })));
const BackupsPage = lazy(() => ops().then((m) => ({ default: m.BackupsPage })));
const UserImport = lazy(() => ops().then((m) => ({ default: m.UserImport })));
const RolesReport = lazy(() => ops().then((m) => ({ default: m.RolesReport })));
const HelpSettings = lazy(() => ops().then((m) => ({ default: m.HelpSettings })));
// the close-out screens (review of Prompt 26): measuring on site, quality, reconciliation, claims, one bill page
const cs = () => import("./closeout/Screens");
const MeasureEntry = lazy(() => cs().then((m) => ({ default: m.MeasureEntry })));
const ClientRolesSettings = lazy(() => cs().then((m) => ({ default: m.ClientRolesSettings })));
const Reconciliation = lazy(() => cs().then((m) => ({ default: m.Reconciliation })));
const LabourClaims = lazy(() => cs().then((m) => ({ default: m.LabourClaims })));
const Bills = lazy(() => cs().then((m) => ({ default: m.Bills })));
const SalesBills = lazy(() => cs().then((m) => ({ default: m.SalesBills })));
const BillPage = lazy(() => cs().then((m) => ({ default: m.BillPage })));
const OldBillRedirect = lazy(() => cs().then((m) => ({ default: m.OldBillRedirect })));
const ChecklistSites = lazy(() => cs().then((m) => ({ default: m.ChecklistSites })));
const Payments = lazy(() => co().then((m) => ({ default: m.Payments })));
const SiteWorkCompletions = lazy(() => co().then((m) => ({ default: m.SiteWorkCompletions })));
const Guarantees = lazy(() => co().then((m) => ({ default: m.Guarantees })));
const Issues = lazy(() => co().then((m) => ({ default: m.Issues })));
const kn = () => import("./knowledge/Pages");
const KnowledgeHome = lazy(() => kn().then((m) => ({ default: m.KnowledgeHome })));
const TemplatePage = lazy(() => kn().then((m) => ({ default: m.TemplatePage })));
const MatchPage = lazy(() => kn().then((m) => ({ default: m.MatchPage })));
const tm = () => import("./team/Pages");
const MyWork = lazy(() => tm().then((m) => ({ default: m.MyWork })));
const Enquiries = lazy(() => tm().then((m) => ({ default: m.Enquiries })));
const AssignmentPage = lazy(() => tm().then((m) => ({ default: m.AssignmentPage })));
const StatusBoard = lazy(() => tm().then((m) => ({ default: m.StatusBoard })));
const MaterialPlan = lazy(() => tm().then((m) => ({ default: m.MaterialPlan })));
const MeasurementBook = lazy(() => tm().then((m) => ({ default: m.MeasurementBook })));
const LabourCheck = lazy(() => tm().then((m) => ({ default: m.LabourCheck })));
const Scorecard = lazy(() => tm().then((m) => ({ default: m.Scorecard })));
const SupervisorDay = lazy(() => tm().then((m) => ({ default: m.SupervisorDay })));
const TeamSettings = lazy(() => tm().then((m) => ({ default: m.TeamSettings })));
const QuotationLibrary = lazy(() => import("./quotations/LibraryPages").then((m) => ({ default: m.QuotationLibrary })));
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
  "/surveys": <SurveysList />,
  "/quotations": <QuotationsList />,
  "/my-work": <MyWork />,
  "/field": <MyDay />,
  "/knowledge": <KnowledgeHome />,
  "/methodology": <MethodologyHome />,
  "/field/team": <TeamMap />,
  "/field/claims": <Claims />,
  "/field/gangs": <GangCheckIn />,
  "/settings/field": <FieldSettings />,
  "/notifications": <Notifications />,
  "/escalated": <Escalated />,
  "/settings/process": <ProcessRules />,
  "/labour-rates": <LabourRates />,
  "/my-notifications": <MyNotificationSettings />,
  "/enquiries": <Enquiries />,
  "/planning/board": <StatusBoard />,
  "/measurements": <MeasurementBook />,
  "/bills": <Bills />,
  "/sales/bills": <SalesBills />,
  "/sales/work-orders": <WorkOrders />,
  "/account": <Account />,
  "/admin/user-import": <UserImport />,
  "/admin/backups": <BackupsPage />,
  "/settings/security": <SecuritySettings />,
  "/settings/roles-report": <RolesReport />,
  "/settings/help": <HelpSettings />,
  "/billing/checklist": <ChecklistSites />,
  "/settings/client-roles": <ClientRolesSettings />,
  "/work-orders": <WorkOrders />,
  "/billing/payments": <Payments />,
  "/guarantees": <Guarantees />,
  "/issues": <Issues />,
  "/labour-check": <LabourCheck />,
  "/scorecard": <Scorecard />,
  "/settings/team": <TeamSettings />,
  "/deliveries": <Deliveries />,
  "/rate-contracts": <RateContracts />,
  "/ready-to-bill": <ReadyToBill />,
  "/new-areas": <NewAreas />,
  "/reports/productivity": <Productivity />,
  "/consumption": <Consumption />,
  "/settings/site-control": <SiteControlSettings />,
  "/settings/quotation-library": <QuotationLibrary />,
  "/settings/survey": <SurveySettings />,
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
  "/settings/issue-log": <IssueLog />,
  "/my-reports": <MyReports />,
};

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/portal/invite/:token" element={<InviteAccept />} />
            <Route path="/set-password/:token" element={<SetPassword />} />
            {/* the delivery receipt page: no login, opened from the QR code on the delivery note */}
            <Route path="/r/:token" element={<ReceiptPage />} />
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
              <Route path="reports" element={<MyReports />} />
              <Route path="*" element={<Navigate to="/portal" replace />} />
            </Route>
            <Route
              element={
                <RequireAuth staff>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<MyWork />} />
              <Route path="/drill" element={<DrillPage />} />
              <Route
                path="/surveys/pilot"
                element={
                  <RequirePermission perms={["survey.view"]}>
                    <PilotReport />
                  </RequirePermission>
                }
              />
              <Route
                path="/deliveries/:id"
                element={
                  <RequirePermission perms={["delivery.view"]}>
                    <DeliveryDetail />
                  </RequirePermission>
                }
              />
              <Route
                path="/sites/:id/new-area"
                element={
                  <RequirePermission perms={["site.update", "site.edit"]}>
                    <NewAreaForm />
                  </RequirePermission>
                }
              />
              <Route
                path="/sites/:id/fronts"
                element={
                  <RequirePermission perms={["site.view"]}>
                    <WorkFronts />
                  </RequirePermission>
                }
              />
              <Route
                path="/quotations/:id"
                element={
                  <RequirePermission perms={["quotation.view"]}>
                    <QuotationEditor />
                  </RequirePermission>
                }
              />
              <Route
                path="/surveys/:id"
                element={
                  <RequirePermission perms={["survey.view"]}>
                    <SurveyDetail />
                  </RequirePermission>
                }
              />
              {MENU.map((item) => (
                <Route key={item.to} path={item.to} element={<RequirePermission perms={item.view ?? item.perms}>{PAGES[item.to] ?? <Placeholder title={item.label} />}</RequirePermission>} />
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
                  ["/quotations/:id/working", ["quotation.view"], <QuotationWorking />],
                  ["/prices/:id", ["tender.margin"], <ProductPrices />],
                  ["/sites/:id/takeoff", ["takeoff.view"], <TakeoffPage />],
                  ["/sites/:id/building", ["building.edit", "site.view"], <BuildingBuilder />],
                  ["/field/days/:id", ["field.track", "field.claims"], <DayMap />],
                  ["/knowledge/templates/:id", ["knowledge.view"], <TemplatePage />],
                  ["/methodology/systems/:id", ["methodology.view"], <MethodSystemPage />],
                  ["/methodology/standards/:id", ["methodology.view"], <StandardPage />],
                  ["/methodology/m/:id", ["methodology.view"], <MethodologyPage />],
                  ["/sites/:id/methodology", ["methodology.site"], <SiteMethodology />],
                  ["/knowledge/match/tender/:id", ["knowledge.view"], <MatchPage />],
                  ["/field/claims/:id", ["field.track", "field.claims"], <ClaimDetail />],
                  ["/assignments/:id", ["jobs.assign", "planning.view"], <AssignmentPage />],
                  ["/sites/:id/material-plan", ["planning.view", "indent.view"], <MaterialPlan />],
                  ["/my-site/:id", ["site.view"], <SupervisorDay />],
                  ["/purchase-orders/new", ["po.edit"], <NewPo />],
                  ["/purchase-orders/:id", ["po.view"], <PoDetail />],
                  ["/stores/:id", ["store.view"], <StoreDetail />],
                  ["/work-orders/:id", ["wo.view"], <WorkOrderPage />],
                  ["/sites/:id/measurements", ["closeout.billing"], <MeasureEntry />],
                  ["/sites/:id/reconciliation", ["closeout.billing"], <Reconciliation />],
                  ["/sites/:id/labour-claims", ["closeout.billing", "closeout.claim_approve"], <LabourClaims />],
                  ["/bills/:id", ["billing.view", "closeout.billing", "closeout.payments"], <BillPage />],
                  ["/sites/:id/zones", ["closeout.site", "closeout.billing"], <SiteZones />],
                  ["/sites/:id/billing-checklist", ["closeout.billing"], <BillingChecklist />],
                  ["/sites/:id/work-completions", ["closeout.billing"], <SiteWorkCompletions />],
                  ["/settings/issue-log/:id", ["issuelog.view"], <IssuePage />],
                ] as [string, string[], JSX.Element][]
              ).map(([path, perms, page]) => (
                <Route key={path} path={path} element={<RequirePermission perms={perms}>{page}</RequirePermission>} />
              ))}
              {/* the two old bill pages are one now: their links open it */}
              <Route path="/bill-tracking" element={<OldBillRedirect />} />
              <Route path="/billing/tracking" element={<OldBillRedirect />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
        <HelperCard />
      </AuthProvider>
    </BrowserRouter>
  );
}
