import { Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import { RequireAuth, RequirePermission } from "./components/Guards";
import Layout from "./components/Layout";
import { MENU } from "./menu";
import { routePerms } from "./routes";
import Login from "./pages/Login";
import Placeholder from "./pages/Placeholder";
import { HelperCard } from "./helper/Helper";
import { PageSkeleton } from "./ui/components";
import { ToastProvider } from "./ui/Overlay";
import { lazyPage, registerPages } from "./ui/prefetch";
// every page in its own chunk: the first load carries the shell, the sign-in and the menu only
const Audit = lazyPage(() => import("./pages/Audit"));
const Channels = lazyPage(() => import("./pages/Channels"));
const Clients = lazyPage(() => import("./pages/Clients"));
const LeadDetail = lazyPage(() => import("./pages/LeadDetail"));
const Leads = lazyPage(() => import("./pages/Leads"));
const Products = lazyPage(() => import("./pages/Products"));
const RateLibrary = lazyPage(() => import("./pages/RateLibrary"));
const Roles = lazyPage(() => import("./pages/Roles"));
const SiteDetail = lazyPage(() => import("./pages/SiteDetail"));
const Sites = lazyPage(() => import("./pages/Sites"));
const SystemDetail = lazyPage(() => import("./pages/SystemDetail"));
const Systems = lazyPage(() => import("./pages/Systems"));
const TcLibrary = lazyPage(() => import("./pages/TcLibrary"));
const TenderDetail = lazyPage(() => import("./pages/TenderDetail"));
const Tenders = lazyPage(() => import("./pages/Tenders"));
const Users = lazyPage(() => import("./pages/Users"));
const Vendors = lazyPage(() => import("./pages/Vendors"));
const Categories = lazyPage(() => import("./pages/settings/Categories"));
const CompanyBanks = lazyPage(() => import("./pages/settings/CompanyBanks"));
const CompanyProfile = lazyPage(() => import("./pages/settings/CompanyProfile"));
const GstinAddresses = lazyPage(() => import("./pages/settings/GstinAddresses"));
const KylasSettingsPage = lazyPage(() => import("./pages/settings/KylasSettings"));
const PurchaseSettings = lazyPage(() => import("./pages/settings/PurchaseSettings"));
const StageTemplates = lazyPage(() => import("./pages/settings/StageTemplates"));
const Tags = lazyPage(() => import("./pages/settings/Tags"));
const UnitsConversions = lazyPage(() => import("./pages/settings/UnitsConversions"));

// the client portal is its own chunk (and its own phone-first layout)
const portal = () => import("./portal/Portal");
const PortalLayout = lazyPage(() => portal().then((m) => ({ default: m.PortalLayout })));
const PortalHome = lazyPage(() => portal().then((m) => ({ default: m.PortalHome })));
const PortalSitePage = lazyPage(() => portal().then((m) => ({ default: m.PortalSitePage })));
const helperPages = () => import("./helper/Pages");
const IssueLog = lazyPage(() => helperPages().then((m) => ({ default: m.IssueLog })));
const IssuePage = lazyPage(() => helperPages().then((m) => ({ default: m.IssuePage })));
const MyReports = lazyPage(() => helperPages().then((m) => ({ default: m.MyReports })));
const InviteAccept = lazyPage(() => portal().then((m) => ({ default: m.InviteAccept })));
const Snags = lazyPage(() => import("./pages/Snags"));
// site survey (with its measuring camera) is its own chunk
const sv = () => import("./survey/SurveyPages");
const SurveysList = lazyPage(() => sv().then((m) => ({ default: m.SurveysList })));
const SurveyDetail = lazyPage(() => sv().then((m) => ({ default: m.SurveyDetail })));
const PilotReport = lazyPage(() => sv().then((m) => ({ default: m.PilotReport })));
const SurveySettings = lazyPage(() => sv().then((m) => ({ default: m.SurveySettings })));
// quotations (editor and library) are their own chunk
const qp = () => import("./quotations/QuotationPages");
const QuotationsList = lazyPage(() => qp().then((m) => ({ default: m.QuotationsList })));
const QuotationEditor = lazyPage(() => qp().then((m) => ({ default: m.QuotationEditor })));
const ReceiptPage = lazyPage(() => import("./receipt/ReceiptPage"));
// rate working, the master price list and labour rates (the director's review, 12 Oct)
const cp = () => import("./costing/Pages");
const QuotationWorking = lazyPage(() => cp().then((m) => ({ default: m.QuotationWorking })));
const ProductPrices = lazyPage(() => cp().then((m) => ({ default: m.ProductPrices })));
const LabourRates = lazyPage(() => cp().then((m) => ({ default: m.LabourRates })));
// AutoCAD takeoff: the drawing viewer and the areas (its own chunk)
const TakeoffPage = lazyPage(() => import("./takeoff/Pages").then((m) => ({ default: m.TakeoffPage })));
// measuring from the drawing and the RA bill from the sheet (its own chunk)
const MeasurePage = lazyPage(() => import("./measure/Pages").then((m) => ({ default: m.MeasurePage })));
// the X-ray 3D building model from the drawing (its own chunk)
const BuildingBuilder = lazyPage(() => import("./xray/Builder"));
const sc = () => import("./sitecontrol/Pages");
const Deliveries = lazyPage(() => sc().then((m) => ({ default: m.Deliveries })));
const DeliveryDetail = lazyPage(() => sc().then((m) => ({ default: m.DeliveryDetail })));
const RateContracts = lazyPage(() => sc().then((m) => ({ default: m.RateContracts })));
const ReadyToBill = lazyPage(() => sc().then((m) => ({ default: m.ReadyToBill })));
const Variations = lazyPage(() => import("./measure/Billing").then((m) => ({ default: m.VariationsPage })));
const NewAreas = lazyPage(() => sc().then((m) => ({ default: m.NewAreas })));
const NewAreaForm = lazyPage(() => sc().then((m) => ({ default: m.NewAreaForm })));
const Productivity = lazyPage(() => sc().then((m) => ({ default: m.Productivity })));
const Consumption = lazyPage(() => sc().then((m) => ({ default: m.Consumption })));
const SiteControlSettings = lazyPage(() => sc().then((m) => ({ default: m.SiteControlSettings })));
const WorkFronts = lazyPage(() => import("./pages/site/WorkFronts"));
const pr = () => import("./process/Pages");
const Notifications = lazyPage(() => pr().then((m) => ({ default: m.Notifications })));
const Escalated = lazyPage(() => pr().then((m) => ({ default: m.Escalated })));
const ProcessRules = lazyPage(() => pr().then((m) => ({ default: m.ProcessRules })));
const MyNotificationSettings = lazyPage(() => pr().then((m) => ({ default: m.MyNotificationSettings })));
const fd = () => import("./field/MyDay");
const MyDay = lazyPage(() => fd().then((m) => ({ default: m.MyDay })));
const fm = () => import("./field/Maps");
const DayMap = lazyPage(() => fm().then((m) => ({ default: m.DayMap })));
const TeamMap = lazyPage(() => fm().then((m) => ({ default: m.TeamMap })));
const fc = () => import("./field/Claims");
const Claims = lazyPage(() => fc().then((m) => ({ default: m.Claims })));
const ClaimDetail = lazyPage(() => fc().then((m) => ({ default: m.ClaimDetail })));
const fa = () => import("./field/Admin");
const GangCheckIn = lazyPage(() => fa().then((m) => ({ default: m.GangCheckIn })));
const FieldSettings = lazyPage(() => fa().then((m) => ({ default: m.FieldSettings })));
const md = () => import("./methodology/Pages");
const MethodologyHome = lazyPage(() => md().then((m) => ({ default: m.MethodologyHome })));
const MethodSystemPage = lazyPage(() => md().then((m) => ({ default: m.SystemPage })));
const StandardPage = lazyPage(() => md().then((m) => ({ default: m.StandardPage })));
const MethodologyPage = lazyPage(() => md().then((m) => ({ default: m.MethodologyPage })));
const SiteMethodology = lazyPage(() => md().then((m) => ({ default: m.SiteMethodology })));
// work orders, client approvals, bill steps, payments, completion and issues (the 16 Oct review)
const co = () => import("./closeout/Pages");
const WorkOrders = lazyPage(() => co().then((m) => ({ default: m.WorkOrders })));
const WorkOrderPage = lazyPage(() => co().then((m) => ({ default: m.WorkOrderPage })));
const SiteZones = lazyPage(() => co().then((m) => ({ default: m.SiteZones })));
const BillingChecklist = lazyPage(() => co().then((m) => ({ default: m.BillingChecklist })));
// go-live: the account, set password, security, backups, user import, roles report, help
const ops = () => import("./ops/Pages");
const SetPassword = lazyPage(() => ops().then((m) => ({ default: m.SetPassword })));
const Account = lazyPage(() => ops().then((m) => ({ default: m.Account })));
const SecuritySettings = lazyPage(() => ops().then((m) => ({ default: m.SecuritySettings })));
const BackupsPage = lazyPage(() => ops().then((m) => ({ default: m.BackupsPage })));
const UserImport = lazyPage(() => ops().then((m) => ({ default: m.UserImport })));
const RolesReport = lazyPage(() => ops().then((m) => ({ default: m.RolesReport })));
const HelpSettings = lazyPage(() => ops().then((m) => ({ default: m.HelpSettings })));
// the close-out screens (review of Prompt 26): measuring on site, quality, reconciliation, claims, one bill page
const cs = () => import("./closeout/Screens");
const MeasureEntry = lazyPage(() => cs().then((m) => ({ default: m.MeasureEntry })));
const ClientRolesSettings = lazyPage(() => cs().then((m) => ({ default: m.ClientRolesSettings })));
const Reconciliation = lazyPage(() => cs().then((m) => ({ default: m.Reconciliation })));
const LabourClaims = lazyPage(() => cs().then((m) => ({ default: m.LabourClaims })));
const Bills = lazyPage(() => cs().then((m) => ({ default: m.Bills })));
const SalesBills = lazyPage(() => cs().then((m) => ({ default: m.SalesBills })));
const BillPage = lazyPage(() => cs().then((m) => ({ default: m.BillPage })));
const OldBillRedirect = lazyPage(() => cs().then((m) => ({ default: m.OldBillRedirect })));
const ChecklistSites = lazyPage(() => cs().then((m) => ({ default: m.ChecklistSites })));
const Payments = lazyPage(() => co().then((m) => ({ default: m.Payments })));
const SiteWorkCompletions = lazyPage(() => co().then((m) => ({ default: m.SiteWorkCompletions })));
const Guarantees = lazyPage(() => co().then((m) => ({ default: m.Guarantees })));
const Issues = lazyPage(() => co().then((m) => ({ default: m.Issues })));
const kn = () => import("./knowledge/Pages");
const KnowledgeHome = lazyPage(() => kn().then((m) => ({ default: m.KnowledgeHome })));
const TemplatePage = lazyPage(() => kn().then((m) => ({ default: m.TemplatePage })));
const MatchPage = lazyPage(() => kn().then((m) => ({ default: m.MatchPage })));
const tm = () => import("./team/Pages");
const MyWork = lazyPage(() => tm().then((m) => ({ default: m.MyWork })));
const Enquiries = lazyPage(() => tm().then((m) => ({ default: m.Enquiries })));
const AssignmentPage = lazyPage(() => tm().then((m) => ({ default: m.AssignmentPage })));
const StatusBoard = lazyPage(() => tm().then((m) => ({ default: m.StatusBoard })));
const MaterialPlan = lazyPage(() => tm().then((m) => ({ default: m.MaterialPlan })));
const MeasurementBook = lazyPage(() => tm().then((m) => ({ default: m.MeasurementBook })));
const LabourCheck = lazyPage(() => tm().then((m) => ({ default: m.LabourCheck })));
const Scorecard = lazyPage(() => tm().then((m) => ({ default: m.Scorecard })));
const SupervisorDay = lazyPage(() => tm().then((m) => ({ default: m.SupervisorDay })));
const TeamSettings = lazyPage(() => tm().then((m) => ({ default: m.TeamSettings })));
const QuotationLibrary = lazyPage(() => import("./quotations/LibraryPages").then((m) => ({ default: m.QuotationLibrary })));
// dashboards and analytics (with their charts) are one chunk
const Dashboard = lazyPage(() => import("./analytics/Dashboard"));
const Home = lazyPage(() => import("./home/Home"));
const TodayReport = lazyPage(() => import("./field/TodayReport"));
const HowItWorks = lazyPage(() => import("./help/HowItWorks"));
const SopPage = lazyPage(() => import("./help/Sop"));
// the component page: in the development build only (the production build leaves it out)
const UiGallery = import.meta.env.DEV ? lazyPage(() => import("./dev/UiGallery")) : null;
const an = () => import("./analytics/Pages");
const SitesAnalytics = lazyPage(() => an().then((m) => ({ default: m.SitesAnalytics })));
const FinanceAnalytics = lazyPage(() => an().then((m) => ({ default: m.FinanceAnalytics })));
const ProfitabilityAnalytics = lazyPage(() => an().then((m) => ({ default: m.ProfitabilityAnalytics })));
const PurchaseAnalytics = lazyPage(() => an().then((m) => ({ default: m.PurchaseAnalytics })));
const LabourAnalytics = lazyPage(() => an().then((m) => ({ default: m.LabourAnalytics })));
const StrategyAnalytics = lazyPage(() => an().then((m) => ({ default: m.StrategyAnalytics })));
const DrillPage = lazyPage(() => an().then((m) => ({ default: m.DrillPage })));
const AlertsPage = lazyPage(() => an().then((m) => ({ default: m.AlertsPage })));
const ReportsPage = lazyPage(() => an().then((m) => ({ default: m.ReportsPage })));
const fin = () => import("./pages/finance/Reports");
const Billing = lazyPage(() => import("./pages/finance/Billing"));
const Payables = lazyPage(() => import("./pages/finance/Payables"));
const PettyCash = lazyPage(() => import("./pages/finance/PettyCash"));
const Payroll = lazyPage(() => import("./pages/finance/Payroll"));
const SiteProfit = lazyPage(() => import("./pages/finance/Reports"));
const Tally = lazyPage(() => fin().then((m) => ({ default: m.Tally })));
const FinanceSettings = lazyPage(() => fin().then((m) => ({ default: m.FinanceSettings })));
const ex = () => import("./pages/execution/Pages");
const AttendanceToday = lazyPage(() => ex().then((m) => ({ default: m.AttendanceToday })));
const LabourMaster = lazyPage(() => ex().then((m) => ({ default: m.LabourMaster })));
const Subcontractors = lazyPage(() => ex().then((m) => ({ default: m.Subcontractors })));
const Assets = lazyPage(() => ex().then((m) => ({ default: m.Assets })));
const DailyReports = lazyPage(() => ex().then((m) => ({ default: m.DailyReports })));
const Checklists = lazyPage(() => ex().then((m) => ({ default: m.Checklists })));
// the material module is its own chunk
const Freight = lazyPage(() => import("./pages/material/Freight"));
const Grns = lazyPage(() => import("./pages/material/Grns"));
const Indents = lazyPage(() => import("./pages/material/Indents"));
const Pos = lazyPage(() => import("./pages/material/Pos"));
const NewPo = lazyPage(() => import("./pages/material/Pos").then((m) => ({ default: m.NewPo })));
const PoDetail = lazyPage(() => import("./pages/material/Pos").then((m) => ({ default: m.PoDetail })));
const Rfqs = lazyPage(() => import("./pages/material/Rfqs"));
const RfqDetail = lazyPage(() => import("./pages/material/Rfqs").then((m) => ({ default: m.RfqDetail })));
const Stores = lazyPage(() => import("./pages/material/Stores"));
const StoreDetail = lazyPage(() => import("./pages/material/Stores").then((m) => ({ default: m.StoreDetail })));
const est = () => import("./estimate/Estimates");
const MaterialLibrary = lazyPage(() => import("./estimate/Library"));
const EstimatesList = lazyPage(() => est().then((m) => ({ default: m.EstimatesList })));
const EstimatePage = lazyPage(() => est().then((m) => ({ default: m.EstimatePage })));
const EstimateDrawing = lazyPage(() => import("./estimate/Drawing"));
const MaterialRequests = lazyPage(() => import("./estimate/Requests"));
const AskMaterial = lazyPage(() => import("./estimate/Requests").then((m) => ({ default: m.AskMaterial })));
const Transfers = lazyPage(() => import("./pages/material/Stores").then((m) => ({ default: m.Transfers })));

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
  "/variations": <Variations />,
  "/reports/productivity": <Productivity />,
  "/consumption": <Consumption />,
  "/settings/site-control": <SiteControlSettings />,
  "/settings/quotation-library": <QuotationLibrary />,
  "/settings/survey": <SurveySettings />,
  "/dashboard": <Home />,
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
  "/material-library": <MaterialLibrary />,
  "/estimates": <EstimatesList />,
  "/material-requests": <MaterialRequests />,
  "/freight": <Freight />,
  "/settings/purchase": <PurchaseSettings />,
  "/admin/users": <Users />,
  "/admin/roles": <Roles />,
  "/admin/audit": <Audit />,
  "/settings/issue-log": <IssueLog />,
  "/my-reports": <MyReports />,
};

registerPages(PAGES);

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <ToastProvider>
        <Suspense fallback={<PageSkeleton />}>
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
              <Route path="sop" element={<SopPage />} />
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
              <Route path="/drill" element={<RequirePermission perms={routePerms("/drill")}><DrillPage /></RequirePermission>} />
              <Route
                path="/surveys/pilot"
                element={
                  <RequirePermission perms={routePerms("/surveys/pilot")}>
                    <PilotReport />
                  </RequirePermission>
                }
              />
              <Route
                path="/deliveries/:id"
                element={
                  <RequirePermission perms={routePerms("/deliveries/:id")}>
                    <DeliveryDetail />
                  </RequirePermission>
                }
              />
              <Route
                path="/sites/:id/new-area"
                element={
                  <RequirePermission perms={routePerms("/sites/:id/new-area")}>
                    <NewAreaForm />
                  </RequirePermission>
                }
              />
              <Route
                path="/sites/:id/fronts"
                element={
                  <RequirePermission perms={routePerms("/sites/:id/fronts")}>
                    <WorkFronts />
                  </RequirePermission>
                }
              />
              <Route
                path="/quotations/:id"
                element={
                  <RequirePermission perms={routePerms("/quotations/:id")}>
                    <QuotationEditor />
                  </RequirePermission>
                }
              />
              <Route
                path="/surveys/:id"
                element={
                  <RequirePermission perms={routePerms("/surveys/:id")}>
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
                  <RequirePermission perms={routePerms("/systems/:id")}>
                    <SystemDetail />
                  </RequirePermission>
                }
              />
              <Route
                path="/tenders/:id"
                element={
                  <RequirePermission perms={routePerms("/tenders/:id")}>
                    <TenderDetail />
                  </RequirePermission>
                }
              />
              <Route
                path="/sites/:id"
                element={
                  <RequirePermission perms={routePerms("/sites/:id")}>
                    <SiteDetail />
                  </RequirePermission>
                }
              />
              <Route
                path="/leads/:id"
                element={
                  <RequirePermission perms={routePerms("/leads/:id")}>
                    <LeadDetail />
                  </RequirePermission>
                }
              />
              {(
                [
                  ["/rfqs/:id", routePerms("/rfqs/:id"), <RfqDetail />],
                  ["/quotations/:id/working", routePerms("/quotations/:id/working"), <QuotationWorking />],
                  ["/prices/:id", routePerms("/prices/:id"), <ProductPrices />],
                  ["/sites/:id/takeoff", routePerms("/sites/:id/takeoff"), <TakeoffPage />],
                  ["/sites/:id/measure", routePerms("/sites/:id/measure"), <MeasurePage />],
                  ["/sites/:id/building", routePerms("/sites/:id/building"), <BuildingBuilder />],
                  ["/field/days/:id", routePerms("/field/days/:id"), <DayMap />],
                  ["/knowledge/templates/:id", routePerms("/knowledge/templates/:id"), <TemplatePage />],
                  ["/methodology/systems/:id", routePerms("/methodology/systems/:id"), <MethodSystemPage />],
                  ["/methodology/standards/:id", routePerms("/methodology/standards/:id"), <StandardPage />],
                  ["/methodology/m/:id", routePerms("/methodology/m/:id"), <MethodologyPage />],
                  ["/sites/:id/methodology", routePerms("/sites/:id/methodology"), <SiteMethodology />],
                  ["/knowledge/match/tender/:id", routePerms("/knowledge/match/tender/:id"), <MatchPage />],
                  ["/field/claims/:id", routePerms("/field/claims/:id"), <ClaimDetail />],
                  ["/assignments/:id", routePerms("/assignments/:id"), <AssignmentPage />],
                  ["/sites/:id/material-plan", routePerms("/sites/:id/material-plan"), <MaterialPlan />],
                  ["/my-site/:id", routePerms("/my-site/:id"), <SupervisorDay />],
                  ["/my-site/:id/report", routePerms("/my-site/:id/report"), <TodayReport />],
                  ["/my-site/:id/material", routePerms("/my-site/:id/material"), <AskMaterial />],
                  ["/estimates/:id", routePerms("/estimates/:id"), <EstimatePage />],
                  ["/estimates/:id/drawing", routePerms("/estimates/:id/drawing"), <EstimateDrawing />],
                  ["/help/how-it-works", routePerms("/help/how-it-works"), <HowItWorks />],
                  ["/help/sop", routePerms("/help/sop"), <SopPage />],
                  ...(UiGallery ? ([["/dev/ui", ["admin.users"], <UiGallery />]] as [string, string[], JSX.Element][]) : []),
                  ["/purchase-orders/new", routePerms("/purchase-orders/new"), <NewPo />],
                  ["/purchase-orders/:id", routePerms("/purchase-orders/:id"), <PoDetail />],
                  ["/stores/:id", routePerms("/stores/:id"), <StoreDetail />],
                  ["/work-orders/:id", routePerms("/work-orders/:id"), <WorkOrderPage />],
                  ["/sites/:id/measurements", routePerms("/sites/:id/measurements"), <MeasureEntry />],
                  ["/sites/:id/reconciliation", routePerms("/sites/:id/reconciliation"), <Reconciliation />],
                  ["/sites/:id/labour-claims", routePerms("/sites/:id/labour-claims"), <LabourClaims />],
                  ["/bills/:id", routePerms("/bills/:id"), <BillPage />],
                  ["/sites/:id/zones", routePerms("/sites/:id/zones"), <SiteZones />],
                  ["/sites/:id/billing-checklist", routePerms("/sites/:id/billing-checklist"), <BillingChecklist />],
                  ["/sites/:id/work-completions", routePerms("/sites/:id/work-completions"), <SiteWorkCompletions />],
                  ["/settings/issue-log/:id", routePerms("/settings/issue-log/:id"), <IssuePage />],
                  ["/dashboard/details", routePerms("/dashboard/details"), <Dashboard />],
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
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
