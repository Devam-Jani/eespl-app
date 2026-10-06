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
  latest_client: string | null;
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
  client_folder: string | null;
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
