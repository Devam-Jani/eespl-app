// Execution: DPR, labour and attendance, work orders, inspections, MOM, assets, budget.

export type DprTask = { id: number; name: string; where: string; status: string; percent: number; photos: { id: number; filename: string }[] };
export type DprAuto = {
  tasks: DprTask[];
  received: { code: string; from: string; items: string }[];
  issued: { code: string; kind: string; for: string | null; items: string; value: string }[];
  labour: { present: number; half_day: number; absent: number; by_trade: Record<string, number>; names: string[] };
  equipment: { asset: string; quantity: string; basis: string; operator: string | null }[];
};

export type Dpr = {
  id: number | null;
  site_id: number;
  site_code: string;
  site_name: string;
  on_date: string;
  weather: string | null;
  work_done: string | null;
  hindrances: string | null;
  next_day_plan: string | null;
  status: "new" | "draft" | "submitted" | "acknowledged";
  submitted_by_name: string | null;
  submitted_at: string | null;
  acknowledged_by_name: string | null;
  auto: DprAuto;
  photos: { id: number; filename: string; caption: string | null }[];
  can_edit: boolean;
  can_acknowledge: boolean;
};

export type DprRow = {
  id: number;
  site_id: number;
  site_code: string;
  site_name: string;
  on_date: string;
  status: string;
  weather: string | null;
  submitted_by_name: string | null;
  photos: number;
};

export type Worker = {
  id: number;
  name: string;
  phone: string | null;
  trade: string;
  type: "own" | "subcontractor";
  subcontractor_id: number | null;
  subcontractor_name: string | null;
  site_id: number | null;
  site_code: string | null;
  daily_wage: string;
  ot_rate_per_hour: string;
  aadhaar_last4: string | null;
  is_active: boolean;
};

export type AttendanceStatus = "present" | "half_day" | "absent";
export type SheetRow = {
  labour_id: number;
  name: string;
  trade: string;
  type: string;
  subcontractor_name: string | null;
  status: AttendanceStatus | null;
  ot_hours: string;
  in_time: string | null;
  out_time: string | null;
  elsewhere: string | null;
  photo: boolean;
};
export type DaySheet = { site_id: number; site_code: string; day: string; rows: SheetRow[]; counts: Record<AttendanceStatus, number>; unmarked: number };

export type MusterRow = {
  labour_id: number;
  name: string;
  trade: string;
  type: string;
  site_id: number;
  site_code: string;
  days: string;
  present: number;
  half_days: number;
  absent: number;
  ot_hours: string;
  wage_due: string;
  daily_wage: string;
  marks: Record<string, string>;
};

export type Measurement = { id: number; on_date: string; qty: string; remark: string | null; status: string; verified_by_name: string | null; photos: number };
export type WoLine = {
  id: number;
  description: string;
  area_scope_id: number | null;
  boq_line_id: number | null;
  unit: string;
  qty: string;
  rate: string;
  amount: string;
  measured: string;
  verified: string;
  billable: string;
  over: boolean;
  measurements: Measurement[];
};
export type WorkOrder = {
  id: number;
  code: string;
  site_id: number;
  site_code: string;
  site_name: string;
  subcontractor_id: number;
  subcontractor_name: string;
  subcontractor_pan: string | null;
  material_by: "eespl" | "subcontractor";
  retention_percent: string;
  tds_percent: string;
  start_date: string | null;
  end_date: string | null;
  tc_template_id: number | null;
  remark: string | null;
  status: string;
  approved_by_name: string | null;
  lines: WoLine[];
  amount: string;
  retention: string;
  tds: string;
  billable_to_date: string;
  retention_to_date: string;
  tds_to_date: string;
  can_edit: boolean;
  can_measure: boolean;
  can_approve: boolean;
  can_change_status: boolean;
  warning?: string | null;
};
export type Subcontractor = {
  id: number;
  name: string;
  pan: string | null;
  gstin: string | null;
  city: string | null;
  is_active: boolean;
  tds_percent: string;
  bank: string | null;
  work_orders: number;
};

export type ChecklistItem = { id: number; text: string; type: "pass_fail" | "number" | "text" | "photo"; required: boolean };
export type Checklist = { id: number; name: string; is_active: boolean; items: ChecklistItem[] };
export type InspectionOut = {
  id: number;
  code: string;
  site_id: number;
  site_code: string;
  template_id: number;
  template_name: string;
  task_id: number | null;
  task_name: string | null;
  task_status: string | null;
  node_name: string | null;
  on_date: string;
  answers: { item_id: number; text: string; type: string; required: boolean; value: string | null }[];
  result: "pass" | "fail" | "pass_with_remarks";
  remark: string | null;
  client_rep: string | null;
  inspected_by_name: string | null;
  has_signature: boolean;
  client_signoff?: "none" | "waiting" | "signed";
  client_signed_name?: string | null;
  photos: { n: number; filename: string; item_id: number | null }[];
};

export type MomPoint = {
  id: number;
  text: string;
  owner_user_id: string | null;
  owner: string | null;
  owner_name: string | null;
  due_date: string | null;
  status: "open" | "done" | "dropped";
  overdue: boolean;
  mom_code?: string;
};
export type MomOut = {
  id: number;
  code: string;
  site_id: number;
  on_date: string;
  title: string;
  venue: string | null;
  attendee_user_ids: string[];
  attendees: string[];
  attendee_others: string[];
  notes: string | null;
  points: MomPoint[];
};

export type AssetOut = {
  id: number;
  code: string;
  name: string;
  category: string;
  make: string | null;
  model: string | null;
  serial_no: string | null;
  purchase_date: string | null;
  purchase_value: string | null;
  ownership: "own" | "hired";
  vendor_id: number | null;
  vendor_name: string | null;
  rate_per_hour: string | null;
  rate_per_day: string | null;
  status: string;
  store_id: number | null;
  site_id: number | null;
  location: string;
  located_since: string | null;
  days_here: number | null;
  overdue: boolean;
  is_active: boolean;
};
export type Usage = {
  id: number;
  asset_id: number;
  asset: string;
  site_id: number;
  site_code: string;
  on_date: string;
  basis: string;
  quantity: string;
  rate: string;
  fuel_litres: string;
  fuel_cost: string;
  operator: string | null;
  amount: string;
};

export type BudgetRow = {
  head: string;
  budget: string | null;
  source: string | null;
  saved: boolean;
  hidden: boolean;
  actual: string;
  variance: string | null;
  percent_used: string | null;
  warn: boolean;
};
export type Budget = {
  site_id: number;
  rows: BudgetRow[];
  cost_hidden: boolean;
  total_budget: string | null;
  total_actual: string;
  tender_suggestion: Record<string, string> | null;
  can_edit: boolean;
};
