export type Page = "overview" | "copilot" | "genie" | "knowledge" | "approvals" | "about";

export interface Me {
  id: string; // keys this person's chat history in the browser
  name: string;
  tiers: string[];
  admin: boolean;
}

export interface Acquirer {
  acquirer_id: string;
  status: string;
  recent_failure_rate: string;
  baseline_failure_rate: string;
  recent_amount: string;
  baseline_daily_amount: string;
  updated_sgt: string;
  data_until_sgt: string | null;
}

export interface PendingApproval {
  approval_id: string;
  run_id: string;
  acquirer_id: string | null;
  batch_id: string;
  payments: string | null;
  total_sgd: string;
  requested_by: string;
  requested_sgt: string;
  expires_in_minutes: string;
  mine: string | boolean;
}

export interface DecidedApproval {
  approval_id: string;
  batch_id: string;
  acquirer_id: string | null;
  payments: string | null;
  total_sgd: string;
  status: string;
  requested_by: string;
  approved_by: string;
  decided_sgt: string | null;
  batch_status: string | null;
  executed_sgt: string | null;
}

/** A question routed from one page to another (for example from the overview), asked once on arrival. */
export interface Incoming {
  page: Page;
  question: string;
  nonce: number;
}

/** GET /api/about: the workspace host, and the paths of what the About page links to (runtime/about.py). */
export interface AboutInfo {
  host: string;
  catalog: string;
  paths: Record<string, string>;
  names: Record<string, string>;
  github: string | null;
  links_generated_at: string | null;
}
