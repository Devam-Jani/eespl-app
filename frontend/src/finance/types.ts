// Finance: contracts and RA bills, invoices, receipts, vendor bills, payments, subcontractor bills,
// petty cash, payroll, profit.

export type Money = string;

export type ContractLine = {
  id: number;
  boq_line_id: number | null;
  item_no: string | null;
  description: string;
  unit: string;
  qty: string;
  rate: string;
  amount: Money;
  is_extra: boolean;
  approved: boolean;
  approved_by_name: string | null;
  done_qty: string;
  billed_qty: string;
};

export type Contract = {
  id: number;
  site_id: number;
  site_code: string;
  site_name: string;
  client_id: number | null;
  client_name: string | null;
  contract_value: Money;
  retention_percent: string;
  advance_amount: Money;
  advance_recovery_percent: string;
  tds_percent: string;
  gst_tds_percent: string;
  gst_percent: string;
  sac: string;
  place_of_supply: string | null;
  client_gstin: string | null;
  billing_address: string | null;
  advance_left: Money;
  lines: ContractLine[];
};

export type RaLine = {
  id: number;
  contract_line_id: number;
  item_no: string | null;
  description: string;
  unit: string;
  boq_qty: string;
  is_extra: boolean;
  previous_qty: string;
  suggested_qty: string;
  qty: string;
  certified_qty: string | null;
  client_qty?: string | null;
  cumulative_qty: string;
  rate: string;
  amount: Money;
  certified_amount: Money | null;
  cumulative_amount: Money;
};

export type RaBill = {
  id: number;
  code: string;
  seq: number;
  contract_id: number;
  site_id: number;
  site_code: string;
  site_name: string;
  client_name: string | null;
  period_from: string | null;
  period_to: string;
  status: "draft" | "submitted" | "certified_by_client" | "rejected_by_client" | "certified" | "invoiced" | "cancelled";
  gross: Money;
  certified_gross: Money | null;
  retention: Money;
  retention_percent: string;
  advance_recovery: Money;
  other_deduction: Money;
  other_deduction_remark: string | null;
  net: Money;
  certified_by_client: string | null;
  client_remark?: string | null;
  lines: RaLine[];
  invoice_id: number | null;
  invoice_number: string | null;
};

export type Invoice = {
  id: number;
  number: string;
  kind: "invoice" | "credit_note";
  status: string;
  invoice_date: string;
  due_date: string | null;
  site_id: number | null;
  site_code: string | null;
  client_id: number;
  client_name: string;
  place_of_supply: string | null;
  interstate: boolean;
  taxable: Money;
  cgst: Money;
  sgst: Money;
  igst: Money;
  total: Money;
  retention: Money;
  advance_recovery: Money;
  settled: Money;
  credited: Money;
  outstanding: Money | null;
  retention_held: Money | null;
  due: Money | null;
  age_days: number | null;
  credit_notes: { id: number; number: string; total: Money }[];
};

export type Receipt = {
  id: number;
  number: string;
  client_name: string;
  on_date: string;
  mode: string;
  ref_no: string | null;
  amount: Money;
  tds_amount: Money;
  gst_tds_amount: Money;
  write_off: Money;
  is_advance: boolean;
  is_retention: boolean;
  allocations: { invoice_id: number; number: string | null; amount: Money }[];
};

export type AgeingRow = { client_id: number; client_name: string; "0-30": Money; "31-60": Money; "61-90": Money; "90+": Money; due: Money; retention_held: Money };

export type VendorBill = {
  id: number;
  number: string;
  kind: string;
  vendor_id: number;
  vendor_name: string;
  bill_no: string;
  bill_date: string;
  due_date: string;
  taxable: Money;
  cgst: Money;
  sgst: Money;
  igst: Money;
  total: Money;
  tds_section: string | null;
  tds_percent: string;
  tds_amount: Money;
  payable: Money;
  paid: Money;
  outstanding: Money;
  status: string;
  match_issues: { message: string; kind: string }[];
  grns: string[];
  lines: { id: number; description: string; qty: string; unit: string | null; rate: string; amount: Money; gst_percent: string; grn_qty: string | null; po_rate: string | null }[];
};

export type Payment = {
  id: number;
  number: string;
  vendor_name: string;
  on_date: string;
  mode: string;
  ref_no: string | null;
  amount: Money;
  status: string;
  approved_by_name: string | null;
  allocations: { vendor_bill_id: number; number: string | null; amount: Money }[];
};

export type SubconBill = {
  id: number;
  number: string;
  wo_code: string;
  subcontractor_name: string;
  bill_date: string;
  gross: Money;
  retention: Money;
  tds: Money;
  material_recovery: Money;
  advance_recovery: Money;
  gst: Money;
  net: Money;
  status: string;
  vendor_bill_number: string | null;
  retention_held_on_wo: Money;
};

export type PettyEntry = {
  id: number;
  number: string;
  kind: "advance" | "expense" | "settlement";
  on_date: string;
  amount: Money;
  site_code: string | null;
  category: string | null;
  paid_to: string | null;
  has_photo: boolean;
  remark: string | null;
  status: string;
  reject_reason: string | null;
};

export type PettyAccount = {
  id: number;
  user_id: string;
  user_name: string;
  advances: Money;
  expenses: Money;
  settlements: Money;
  pending: Money;
  balance: Money;
  entries?: PettyEntry[];
};

export type Payslip = {
  id: number;
  user_id: string;
  user_name: string;
  days_in_month: number;
  worked_days: number;
  leave_days: string;
  lop_days: string;
  paid_days: string;
  basic: Money;
  hra: Money;
  other_allowance: Money;
  gross: Money;
  pf_employee: Money;
  pf_employer: Money;
  esi_employee: Money;
  esi_employer: Money;
  pt: Money;
  advance_recovery: Money;
  net: Money;
};

export type PayrollRun = { id: number; month: string; status: "draft" | "locked"; payslips: Payslip[]; totals: Record<string, Money> };

export type Profit = {
  site_id: number;
  site_code: string;
  site_name: string;
  billed: Money;
  certified: Money;
  received: Money;
  advance_received: Money;
  retention_held: Money;
  cost: Record<string, Money>;
  cost_total: Money;
  salary_hidden: boolean;
  gross_profit: Money;
  margin_percent: string | null;
  over_cost: boolean;
  contract_value: Money | null;
  budget_at_completion: Money | null;
  projected_profit: Money | null;
  projected_margin_percent: string | null;
};

export type FinanceLookups = {
  banks: { id: number; name: string }[];
  sites: { id: number; code: string; name: string }[];
  clients: { id: number; name: string }[];
  permissions: Record<string, string>;
};
