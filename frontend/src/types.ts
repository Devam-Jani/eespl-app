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
