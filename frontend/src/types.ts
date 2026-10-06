import type { Scope } from "./api";

export type RoleRef = { id: number; code: string; name: string };

export type Me = {
  user: { id: string; email: string; full_name: string; phone: string | null };
  roles: RoleRef[];
  permissions: Record<string, Scope>;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
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
  category: string;
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
  score: number;
};

export type LibraryLine = {
  id: number;
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
};

export type Clause = {
  id: number;
  text: string;
  category: string;
  usage_count: number;
  default_include: boolean;
  sort_order: number;
  is_active: boolean;
};

export type TemplateSummary = { id: number; name: string; is_default: boolean; clause_count: number };
export type Template = { id: number; name: string; is_default: boolean; clauses: Clause[] };
