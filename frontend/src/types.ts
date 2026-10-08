import type { Scope } from "./api";

export type RoleRef = { id: number; code: string; name: string };

export type Me = {
  user: { id: string; email: string | null; full_name: string; phone: string | null };
  roles: RoleRef[];
  permissions: Record<string, Scope>;
};

export type User = {
  id: string;
  email: string | null;
  full_name: string;
  phone: string | null;
  job_title: string | null;
  kylas_user_id: number | null;
  has_password: boolean;
  is_active: boolean;
  locked_until: string | null;
  last_login_at: string | null;
  created_at: string;
  roles: RoleRef[];
};

export type Role = {
  id: number;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions_locked: boolean;
  permissions: Record<string, Scope>;
  user_count: number;
};

export type Permission = { code: string; module: string; description: string | null };

export type AuditEntry = {
  id: number;
  at: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  ip: string | null;
};

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type Contact = {
  id?: number;
  name: string;
  designation: string | null;
  phone: string | null;
  email: string | null;
  is_primary: boolean;
};

export type Client = {
  id: number;
  name: string;
  type: string;
  gstin: string | null;
  pan: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  created_by: string | null;
  contacts: Contact[];
};

export type Price = {
  id: number;
  purchase_rate: string;
  freight_per_unit: string;
  effective_from: string;
  note: string | null;
  created_at: string;
};

export type Product = {
  id: number;
  code: string;
  name: string;
  brand: string | null;
  category_id: number | null;
  category: string | null;
  unit: string;
  pack_size: string | null;
  gst_percent: string;
  hsn_code: string | null;
  reorder_level?: string | null;
  is_active: boolean;
  cost: { current_price: Price | null } | null;
};

export type ComponentPublic = {
  product_id: number;
  product_code: string;
  product_name: string;
  brand: string | null;
  unit: string;
};

export type ComponentCost = ComponentPublic & { consumption_per_unit: string; wastage_percent: string };

export type System = {
  id: number;
  code: string;
  name: string;
  description: string | null;
  unit: string;
  is_active: boolean;
  rate: string | null;
  rate_error: string | null;
  components: ComponentPublic[];
  cost: {
    surface_prep_per_unit: string;
    labour_rate: string;
    labour_unit: string;
    default_margin_percent: string;
    components: ComponentCost[];
  } | null;
};

export type RateBreakdown = {
  system_id: number;
  unit: string;
  components: {
    product_id: number;
    product_name: string;
    unit: string;
    consumption_per_unit: string;
    wastage_percent: string;
    quantity_with_wastage: string;
    purchase_rate: string;
    freight_per_unit: string;
    landed_rate: string;
    cost: string;
  }[];
  material_cost: string;
  surface_prep: string;
  labour_rate: string;
  labour_unit: string;
  labour_per_unit: string;
  base_cost: string;
  margin_percent: string;
  margin_amount: string;
  rate: string;
};

export type Unit = { code: string; name: string; aliases: string[] };

export type LibraryHit = {
  id: number;
  description: string;
  unit: string | null;
  unit_raw: string | null;
  boq_count: number;
  latest_rate: string | null;
  min_rate: string | null;
  median_rate: string | null;
  max_rate: string | null;
  latest_channel: string | null;
  product_make: string | null;
  needs_check: boolean;
  check_note: string | null;
  is_excluded: boolean;
  excluded_reason: string | null;
  is_competitor: boolean;
  suggested_rate: string | null;
  score: number;
};

export type LibrarySearch = {
  items: LibraryHit[];
  took_ms: number;
  has_more: boolean;
  next_offset: number;
  cut_applied: boolean;
};

export type ItemRef = { id: number; description: string; unit: string | null };

export type LibraryItemDetail = Omit<LibraryHit, "score"> & {
  exclusion_source: string | null;
  unit_manual: boolean;
  stats_from_lines: boolean;
  merged_into: ItemRef | null;
  merged_items: ItemRef[];
};

export type LibraryLine = {
  id: number;
  library_item_id: number | null;
  channel: string | null;
  file: string;
  sheet: string | null;
  row: number | null;
  item_no: string | null;
  parent_item: string | null;
  description: string;
  unit_raw: string | null;
  unit: string | null;
  qty: string | null;
  qty_note: string | null;
  rate: string | null;
  product_make: string | null;
  remarks: string | null;
  from_eespl_file: boolean;
  needs_check: boolean;
  check_note: string | null;
  is_excluded: boolean;
  excluded_reason: string | null;
  is_competitor: boolean;
};

export type ClauseVariant = { id: number; text: string; own_usage_count: number };

export type HiddenReason = "not_a_clause" | "client_checklist" | "project_specific" | "manual";

export type Clause = {
  id: number;
  text: string;
  category: string;
  usage_count: number;
  own_usage_count: number;
  default_include: boolean;
  sort_order: number;
  status: "active" | "hidden";
  hidden_reason: HiddenReason | null;
  merged_into_id: number | null;
  needs_review: boolean;
  review_note: string | null;
  variant_count: number;
  variants: ClauseVariant[];
};

export type TemplateSummary = { id: number; name: string; is_default: boolean; clause_count: number };
export type Template = { id: number; name: string; is_default: boolean; clauses: Clause[] };

export type Category = {
  id: number;
  kind: "work" | "material";
  name: string;
  parent_id: number | null;
  sort_order: number;
  is_active: boolean;
  product_count: number;
};

export type TagModule = "material" | "petty_spend" | "work_order" | "issue";
export type Tag = { id: number; module: TagModule; name: string; is_archived: boolean };

export type Conversion = {
  id: number;
  from_unit: string;
  to_unit: string;
  factor: string;
  product_id: number | null;
  product_name: string | null;
};

export type BankAccount = {
  id: number;
  account_name: string;
  bank: string | null;
  branch: string | null;
  is_primary: boolean;
  account_number: string | null;
  ifsc: string | null;
  masked: boolean;
};

export type VendorProduct = {
  id: number;
  product_id: number;
  product_code: string;
  product_name: string;
  unit: string;
  last_rate: string | null;
  lead_time_days: number | null;
};

export type Vendor = {
  id: number;
  name: string;
  type: string;
  gstin: string | null;
  pan: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  payment_terms_days: number | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  contacts: Contact[];
  bank_accounts: BankAccount[];
  products: VendorProduct[];
};

export type CompanyProfile = {
  legal_name: string | null;
  trade_name: string | null;
  pan: string | null;
  tan: string | null;
  tds_percent: string | null;
  cin: string | null;
  email: string | null;
  phone: string | null;
  website: string | null;
  default_gst_percent: string;
  pricing_threshold: string;
  rate_policy: string;
  has_logo: boolean;
  updated_at: string;
};

export type Gstin = { id: number; gstin: string; state: string; address: string; is_default: boolean };

export type CompanyBank = {
  id: number;
  account_name: string;
  account_number: string;
  ifsc: string;
  bank: string | null;
  branch: string | null;
  is_default: boolean;
};

// --- tenders ---

export type TenderStatus = "draft" | "submitted" | "won" | "lost" | "dropped";

export type Tender = {
  id: number;
  code: string;
  name: string;
  client_id: number | null;
  client_name: string | null;
  channel_id: number | null;
  channel_name: string | null;
  site_name: string | null;
  site_city: string | null;
  site_state: string | null;
  received_on: string | null;
  due_on: string | null;
  overdue: boolean;
  owner_id: string | null;
  owner_name: string | null;
  members: { user_id: string; full_name: string }[];
  status: TenderStatus;
  lost_reason: string | null;
  lost_to: string | null;
  lost_note?: string | null;
  decided_at?: string | null;
  quoted_total: string;
  tc_template_id: number | null;
  notes: string | null;
  created_at: string;
  revision: number;
  revision_label: string;
  site_id: number | null;
  kylas_won_lead: string | null;
  submitted_revisions: number;
  // only with tender.margin; null when no line is system-priced
  cost_total?: string | null;
  margin_amount?: string | null;
};

export type ChannelType = "salesperson" | "partner" | "manufacturer" | "other";

export type Channel = {
  id: number;
  name: string;
  type: ChannelType;
  is_active: boolean;
  notes: string | null;
  library_lines: number;
  tenders: number;
};

export type TenderLookups = {
  clients: { id: number; name: string }[];
  channels: { id: number; name: string; type: ChannelType }[];
  users: { id: string; full_name: string }[];
  tc_templates: { id: number; name: string; is_default: boolean }[];
};

export type LineStatus = "unpriced" | "suggested" | "priced" | "not_quoted";

export type BoqLine = {
  id: number;
  section_id: number | null;
  sort_order: number;
  client_item_no: string | null;
  description: string;
  unit: string | null;
  unit_raw: string | null;
  qty: string | null;
  qty_note: "QRO" | "NQ" | null;
  client_product: string | null;
  client_remarks: string | null;
  client_file_rate: string | null;
  client_material_rate: string | null;
  client_application_rate: string | null;
  source_page: number | null;
  source_page_to: number | null;
  rate: string | null;
  amount: string | null;
  our_remarks: string | null;
  our_product: string | null;
  status: LineStatus;
  suggestion_score: string | null;
  // only with tender.margin
  source?: "system" | "library" | "manual" | null;
  system_id?: number | null;
  library_item_id?: number | null;
  cost_rate?: string | null;
  margin_percent?: string | null;
};

export type BoqSection = { id: number; title: string; note: string | null; sort_order: number; total: string };

export type BoqTotals = {
  subtotal: string;
  gst_percent: string;
  gst: string;
  grand_total: string;
  counts: Record<string, number>;
  cost_total?: string | null;
  margin_amount?: string | null;
};

export type Boq = { sections: BoqSection[]; lines: BoqLine[]; totals: BoqTotals };

export type RateHistory = {
  policy: string;
  used: string;
  latest_rate: string | null;
  median_rate: string | null;
  n_boqs: number;
  channel_last_rate: string | null;
  sources: { channel: string | null; file: string; date: string | null; rate: string }[];
  sources_total: number;
  above_median_percent: string | null;
  warning: boolean;
  // only with tender.margin
  min_rate?: string | null;
  max_rate?: string | null;
};

export type Candidate = {
  id: number;
  rank: number;
  rate: string;
  score: string;
  reason: string;
  details: RateHistory | null;
  source?: "system" | "library";
  ref_id?: number;
  cost_rate?: string | null;
  margin_percent?: string | null;
};

export type LibraryStat = {
  library_item_id: number;
  description: string;
  unit: string | null;
  boq_count: number;
  latest_rate: string | null;
  min_rate: string | null;
  median_rate: string | null;
  max_rate: string | null;
  latest_channel: string | null;
};

export type SystemBreakdown = {
  system_id: number;
  code?: string;
  name: string;
  unit?: string;
  components?: { product: string; qty: string; landed_rate: string; cost: string }[];
  material_cost?: string;
  surface_prep?: string;
  labour_per_unit?: string;
  base_cost?: string;
  margin_percent?: string;
  rate?: string;
  error?: string;
};

export type LineDetail = {
  line: BoqLine;
  candidates: Candidate[];
  library_stats?: LibraryStat[];
  system_breakdown?: SystemBreakdown | null;
};

export type ColumnGuess = { column: number; letter: string; header: string; confidence: number; alternatives: string[] };

export type ImportPreview = {
  upload_id: string;
  filename: string;
  sheets: { name: string; header_row: number; score: number }[];
  sheet: string;
  header_row: number;
  header: { column: number; letter: string; text: string }[];
  column_map: Record<string, ColumnGuess>;
  rows: Record<string, unknown>[];
  counts: {
    lines: number;
    sections: number;
    qro: number;
    nq: number;
    skipped: number;
    skipped_by_reason: Record<string, number>;
    unrecognised_units: Record<string, number>;
  };
  existing_lines: number;
  page_count: number | null;
};

export type ImportReport = {
  import_id: number;
  lines: number;
  sections: number;
  qro: number;
  nq: number;
  skipped: number;
  skipped_by_reason: Record<string, number>;
  unrecognised_units: Record<string, number>;
  kept_prices: number;
};

export type SuggestResult = {
  lines_considered: number;
  suggested: number;
  left_unpriced: number;
  skipped_priced: number;
  threshold: string;
};

export type TenderTc = {
  id: number;
  clause_id: number | null;
  category: string | null;
  text: string;
  text_override: string | null;
  sort_order: number;
};

export type Revision = {
  rev_no: number;
  label: string;
  submitted_at: string;
  submitted_by_name: string | null;
  note: string | null;
  subtotal: string;
  grand_total: string;
  lines: number;
};

export type RevisionCompare = {
  a: string;
  b: string;
  lines: {
    item_no: string | null;
    description: string;
    change: "added" | "removed" | "changed" | "same";
    rate_a: string | null;
    rate_b: string | null;
    rate_delta: string | null;
    amount_a: string | null;
    amount_b: string | null;
    amount_delta: string | null;
  }[];
  subtotal_a: string;
  subtotal_b: string;
  subtotal_delta: string;
  grand_total_a: string;
  grand_total_b: string;
  grand_total_delta: string;
};

export const RATE_POLICIES: Record<string, string> = {
  channel_median: "Same channel's median, else the median",
  median: "Median of all BOQs",
  channel_last: "Same channel's last rate, else the median",
  lower_latest_median: "Lower of latest and median",
  latest: "Latest rate",
  trimmed_mean: "Trimmed mean (top and bottom 10% dropped)",
};

// --- sites ---

export type SiteStatus = "planned" | "active" | "on_hold" | "completed" | "closed";

export type Site = {
  id: number;
  code: string;
  name: string;
  client_id: number | null;
  client_name: string | null;
  channel_id: number | null;
  channel_name: string | null;
  tender_id: number | null;
  tender_code: string | null;
  address: string | null;
  city: string | null;
  state: string | null;
  lat: string | null;
  lng: string | null;
  start_date: string | null;
  target_date: string | null;
  late: boolean;
  status: SiteStatus;
  site_incharge_id: string | null;
  incharge_name: string | null;
  notes: string | null;
  source: "app" | "powerplay";
  source_ref: string | null;
  progress_percent: string;
  members: { user_id: string; full_name: string; role_on_site: string }[];
  created_at: string;
};

export type SiteLookups = {
  clients: { id: number; name: string }[];
  channels: { id: number; name: string }[];
  users: { id: string; full_name: string }[];
  templates: { id: number; name: string }[];
};

export type SiteNode = {
  id: number;
  parent_id: number | null;
  kind: string;
  name: string;
  path: string;
  sort_order: number;
  level_no: number | null;
  area_sqm: string | null;
  meta: Record<string, unknown> | null;
  progress_percent: string;
};

export type TemplateStep = {
  id?: number;
  sort_order?: number;
  name: string;
  weight_percent: string;
  needs_photo: boolean;
  needs_inspection: boolean;
  hold_point: boolean;
  typical_days: number;
  checklist_template_id?: number | null;
};

export type StageTemplate = {
  id: number;
  name: string;
  system_id: number | null;
  system_name: string | null;
  work_category_id: number | null;
  work_category_name: string | null;
  keywords: string | null;
  is_active: boolean;
  steps: TemplateStep[];
  total_days: number;
};

export type AreaScope = {
  id: number;
  node_id: number;
  node_path: string;
  boq_line_id: number | null;
  stage_template_id: number;
  stage_template_name: string;
  qty: string;
  unit: string | null;
  progress_percent: string;
  tasks: number;
  started: number;
};

export type ScopeLine = {
  boq_line_id: number;
  item_no: string | null;
  description: string;
  unit: string | null;
  boq_qty: string | null;
  qty_note: string | null;
  suggested_template_id: number | null;
  assigned: string;
  difference: string;
  state: "ok" | "under" | "over" | "no_qty";
  scopes: AreaScope[];
};

export type ScopeOverview = { lines: ScopeLine[]; other_scopes: AreaScope[] };

export type SiteTask = {
  id: number;
  node_id: number | null;
  node_path: string | null;
  area_scope_id: number | null;
  step_id: number | null;
  checklist_template_id?: number | null;
  name: string;
  sort_order: number;
  planned_start: string | null;
  planned_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  status: "not_started" | "in_progress" | "done" | "certified" | "blocked";
  late: boolean;
  assignee_id: string | null;
  assignee_name: string | null;
  progress_percent: string;
  parent_task_id: number | null;
  depends_on: number[];
  weight_percent: string | null;
  needs_photo: boolean;
  needs_inspection: boolean;
  hold_point: boolean;
  remark: string | null;
  inspection: { item: string; passed: boolean | null }[] | null;
  certified_at: string | null;
  photos: { id: number; filename: string; uploaded_at: string; share_with_client?: boolean }[];
};

export type DrawingRevision = {
  id: number;
  rev: string;
  filename: string;
  size_bytes: number;
  status: "draft" | "submitted" | "approved" | "rejected";
  uploaded_by_name: string | null;
  uploaded_at: string;
  approved_by_name: string | null;
  approved_at: string | null;
  remark: string | null;
};

export type Drawing = {
  id: number;
  title: string;
  discipline: string;
  node_id: number | null;
  node_path: string | null;
  latest_approved: DrawingRevision | null;
  latest: DrawingRevision | null;
  revisions: DrawingRevision[];
  share_with_client?: boolean;
};

// --- CRM leads ---

export type LeadStatus = "new" | "contacted" | "site_visit" | "quoted" | "won" | "lost" | "junk";
export type KylasSync = "disabled" | "pending" | "synced" | "failed";

export type LeadDuplicate = { id: number; code: string; contact_name: string; status: string };

export type Lead = {
  id: number;
  code: string;
  contact_name: string;
  phone: string | null;
  email: string | null;
  company: string | null;
  city: string | null;
  state: string | null;
  lead_source: string;
  channel_id: number | null;
  channel_name: string | null;
  client_id: number | null;
  client_name: string | null;
  requirement: string | null;
  system_id: number | null;
  work_category_id: number | null;
  est_area_sqm: string | null;
  est_value: string | null;
  status: LeadStatus;
  owner_id: string | null;
  owner_name: string | null;
  created_by_name: string | null;
  next_follow_up: string | null;
  follow_up_due: boolean;
  tender_id: number | null;
  tender_code: string | null;
  kylas_lead_id: number | null;
  kylas_sync_status: KylasSync;
  kylas_last_error: string | null;
  kylas_synced_at: string | null;
  kylas_forecasting: string | null;
  kylas_converted_at: string | null;
  kylas_won_at: string | null;
  lost_reason?: string | null;
  lost_to?: string | null;
  lost_note?: string | null;
  created_at: string;
  duplicates: LeadDuplicate[];
};

export type LeadDetail = Lead & {
  activities: { id: number; type: string; text: string; at: string; by_name: string | null }[];
};

export type LeadLookups = {
  channels: { id: number; name: string }[];
  clients: { id: number; name: string }[];
  users: { id: string; full_name: string }[];
  systems: { id: number; name: string }[];
  work_categories: { id: number; name: string }[];
};

export type KylasSettings = {
  enabled_in_env: boolean;
  api_key: string;
  base_url: string;
  active: boolean;
  inactive_reason: string | null;
  source_id: number | null;
  owner_rule: string;
  default_owner_id: number | null;
  deal_pipeline_id: number | null;
  won_stage_id: number | null;
  lead_code_field: string;
  category_field: string;
  junk_reasons: string[];
  queue: Record<string, number>;
};
