// Material: indents, RFQs, purchase orders, GRNs, stores, transfers, issues, freight.

export type Perms = Record<string, string>;

export type PurchaseSettings = {
  po_approval_limit: string;
  allow_negative_stock: boolean;
  grn_approval_levels: number;
  po_tc_template_id: number | null;
};

export type ProductPick = { id: number; code: string; name: string; unit: string; gst_percent: string };
export type VendorPick = { id: number; name: string; gstin: string | null; state: string | null };
export type StorePick = { id: number; name: string; kind: "godown" | "site"; site_id: number | null };

export type MaterialLookups = {
  sites: { id: number; code: string; name: string }[];
  stores: StorePick[];
  products: ProductPick[];
  vendors: VendorPick[];
  units: string[];
  gstins: { id: number; gstin: string; state: string; is_default: boolean }[];
  tc_templates: { id: number; name: string }[];
  settings: PurchaseSettings;
  permissions: Perms;
};

export type StoreRow = {
  id: number;
  name: string;
  kind: "godown" | "site";
  site_id: number | null;
  site_code: string | null;
  address: string | null;
  gstin_address_id: number | null;
  is_active: boolean;
  items: number;
  value: string;
};

export type StockRow = {
  product_id: number;
  product_code: string;
  product_name: string;
  unit: string;
  qty: string;
  avg_rate: string;
  value: string;
};

export type LedgerRow = {
  id: number;
  at: string;
  product_id: number;
  product_name: string;
  qty: string;
  unit: string;
  rate: string;
  value: string;
  ref_type: string;
  ref_id: number | null;
  ref_code: string | null;
  note: string | null;
  balance: string;
};

export type IndentStatus = "draft" | "submitted" | "approved" | "partly_ordered" | "ordered" | "closed" | "rejected" | "cancelled";

export type IndentLine = {
  id: number;
  product_id: number | null;
  product_name: string | null;
  free_text: string | null;
  qty: string;
  unit: string;
  base_qty: string;
  base_unit: string | null;
  boq_line_id: number | null;
  area_scope_id: number | null;
  remark: string | null;
  ordered_qty: string;
  received_qty: string;
};

export type Indent = {
  id: number;
  code: string;
  site_id: number;
  site_code: string;
  site_name: string;
  store_id: number;
  required_by: string | null;
  priority: "normal" | "urgent";
  status: IndentStatus;
  remark: string | null;
  reject_reason: string | null;
  created_at: string;
  created_by_name: string | null;
  approved_at: string | null;
  lines: IndentLine[];
  can_edit: boolean;
  can_approve: boolean;
};

export type QuoteCell = {
  vendor_id: number;
  rate: string;
  gst_percent: string;
  freight: string;
  lead_days: number | null;
  landed_rate: string;
  lowest: boolean;
};

export type Rfq = {
  id: number;
  code: string;
  due_date: string | null;
  status: "draft" | "sent" | "closed" | "cancelled";
  remark: string | null;
  created_at: string;
  indent_ids: number[];
  indent_codes: string[];
  vendors: { vendor_id: number; name: string; freight: string; total: string }[];
  lines: {
    id: number;
    indent_line_id: number | null;
    product_id: number;
    product_name: string;
    qty: string;
    unit: string;
    chosen_vendor_id: number | null;
    choice_reason: string | null;
    quotes: QuoteCell[];
  }[];
  po_ids: number[];
};

export type PoStatus = "draft" | "pending_approval" | "approved" | "sent" | "partly_received" | "received" | "closed" | "cancelled";

export type PoLine = {
  id: number;
  indent_line_id: number | null;
  product_id: number;
  product_code: string;
  product_name: string;
  qty: string;
  unit: string;
  base_qty: string;
  rate: string;
  discount_percent: string;
  gst_percent: string;
  amount: string;
  received_qty: string;
  hsn_code: string | null;
  indent_qty: string | null;
  contract_rate: string | null;
  above_contract_percent: string | null;
  rate_reason: string | null;
};

export type ChargeKind = "freight" | "loading" | "unloading" | "packing" | "other";

export type PoCharge = {
  id: number;
  kind: ChargeKind;
  description: string | null;
  amount: string;
  gst_percent: string;
  add_to_cost: boolean;
};

export type Po = {
  id: number;
  code: string;
  vendor_id: number;
  vendor_name: string;
  vendor_gstin: string | null;
  from_gstin_id: number | null;
  from_gstin: string | null;
  store_id: number;
  store_name: string;
  rfq_id: number | null;
  po_date: string;
  expected_delivery: string | null;
  payment_terms: string | null;
  remark: string | null;
  status: PoStatus;
  interstate: boolean;
  approved_at: string | null;
  approved_by_name: string | null;
  sent_at: string | null;
  created_at: string;
  created_by_name: string | null;
  subtotal: string;
  discount_total: string;
  taxable: string;
  cgst: string;
  sgst: string;
  igst: string;
  charges_total: string;
  round_off: string;
  grand_total: string;
  indent_ids: number[];
  lines: PoLine[];
  charges: PoCharge[];
  approval_limit: string;
  vendor_registered: boolean;
  gstin_missing: boolean;
  warnings: string[];
  needs_approver: boolean;
  can_edit: boolean;
  can_approve: boolean;
};

export type GrnLine = {
  id: number;
  po_line_id: number | null;
  product_id: number;
  product_name: string;
  unit: string;
  ordered_qty: string | null;
  received_qty: string;
  invoice_qty: string | null;
  accepted_qty: string;
  rejected_qty: string;
  reason: string | null;
  rate: string;
  landed_rate: string | null;
  base_unit: string;
};

export type Grn = {
  id: number;
  code: string;
  po_id: number | null;
  po_code: string | null;
  store_id: number;
  store_name: string;
  vendor_id: number;
  vendor_name: string;
  challan_no: string | null;
  invoice_no: string | null;
  invoice_date: string | null;
  invoice_amount: string | null;
  vehicle_no: string | null;
  received_at: string;
  remark: string | null;
  status: "draft" | "submitted" | "approved" | "rejected";
  levels_required: number;
  approvals: number;
  reject_reason: string | null;
  created_at: string;
  created_by_name: string | null;
  lines: GrnLine[];
  photos: { id: number; kind: string; filename: string }[];
  can_edit: boolean;
  can_approve: boolean;
};

export type Transfer = {
  id: number;
  code: string;
  from_store_id: number;
  from_store_name: string;
  to_store_id: number;
  to_store_name: string;
  status: "draft" | "dispatched" | "received" | "cancelled";
  vehicle_no: string | null;
  transporter: string | null;
  freight_amount: string;
  remark: string | null;
  created_at: string;
  dispatched_at: string | null;
  received_at: string | null;
  lines: {
    id: number;
    product_id: number;
    product_name: string;
    unit: string;
    qty_sent: string;
    qty_received: string | null;
    shortage_qty: string;
    shortage_reason: string | null;
    rate: string | null;
  }[];
  can_dispatch: boolean;
  can_receive: boolean;
};

export type Issue = {
  id: number;
  code: string;
  kind: "issue" | "return";
  store_id: number;
  store_name: string;
  site_id: number;
  task_id: number | null;
  task_name: string | null;
  area_scope_id: number | null;
  issued_on: string;
  remark: string | null;
  created_at: string;
  lines: { product_id: number; product_name: string; unit: string; qty: string; rate: string; value: string }[];
};

export type FreightRow = {
  id: number;
  source: "po" | "transfer" | "bill";
  ref_code: string | null;
  site_id: number | null;
  site_code: string | null;
  direction: "inbound" | "godown_to_site" | "other";
  on_date: string;
  amount: string;
  gst_percent: string;
  transporter: string | null;
  vehicle_no: string | null;
  bill_no: string | null;
  remark: string | null;
};

export type FreightReportRow = {
  site_id: number | null;
  site_code: string | null;
  site_name: string | null;
  month: string;
  inbound: string;
  godown_to_site: string;
  other: string;
  total: string;
};

export type SiteMaterialSummary = {
  store: StoreRow | null;
  stock: StockRow[];
  freight: { inbound: string; godown_to_site: string; other: string; total: string };
  issued_value: string;
  returned_value: string;
  permissions: Perms;
};
