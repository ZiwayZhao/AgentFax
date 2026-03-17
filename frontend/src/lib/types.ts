/* AgentFax TypeScript types — mirrors backend data models */

// ── Trust & Privacy ──────────────────────────────────────

export const TrustTier = {
  UNTRUSTED: 0,
  KNOWN: 1,
  INTERNAL: 2,
  PRIVILEGED: 3,
  SYSTEM: 4,
} as const;
export type TrustTier = (typeof TrustTier)[keyof typeof TrustTier];

export const PrivacyTier = {
  L1_PUBLIC: 1,
  L2_TRUSTED: 2,
  L3_PRIVATE: 3,
} as const;
export type PrivacyTier = (typeof PrivacyTier)[keyof typeof PrivacyTier];

// ── Stats / Overview ─────────────────────────────────────

export interface AgentProfile {
  agent_id: string;
  wallet: string;
  display_name: string;
  agent_number: number;
}

export interface DashboardStats {
  agent: AgentProfile;
  inbox_count: number;
  outbox_count: number;
  task_count: number;
  peer_count: number;
  active_sessions: number;
  running_workflows: number;
  message_types: Record<string, number>;
  task_states: Record<string, number>;
  uptime_seconds?: number;
}

// ── Peers ────────────────────────────────────────────────

export interface Peer {
  name: string;
  wallet: string;
  last_seen: string;
  is_online: boolean;
  trust_tier: TrustTier;
  latency_ms: number | null;
  skills: string[];
}

export interface ReputationSummary {
  peer_id: string;
  total_interactions: number;
  successes: number;
  failures: number;
  success_rate: number;
  avg_latency_ms: number | null;
  first_seen: string;
  last_seen: string;
  current_tier: TrustTier;
}

export interface PeerDetail extends Peer {
  reputation: Partial<ReputationSummary>;
  skill_cards: SkillCardBasic[];
  error?: string;
}

export interface SkillCardBasic {
  skill_name: string;
  skill_version?: string;
  description?: string;
  min_trust_tier?: number;
  max_context_privacy_tier?: string;
  tags?: string[];
  _peer_id?: string;
  provider?: { agent_id: string; wallet: string; display_name: string };
}

// ── Tasks ────────────────────────────────────────────────

export interface Task {
  task_id: string;
  skill: string;
  state: 'pending' | 'accepted' | 'in_progress' | 'completed' | 'failed' | 'cancelled' | 'timed_out';
  peer_name: string;
  peer_wallet: string;
  input_data: unknown;
  output_data: unknown;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
  completed_at: string | null;
  role: 'executor' | 'requester';
  session_id: string | null;
}

// ── Sessions ─────────────────────────────────────────────

export type SessionState =
  | 'proposed'
  | 'active'
  | 'closing'
  | 'closed'
  | 'completed'
  | 'expired'
  | 'rejected';

export interface Session {
  session_id: string;
  peer_id: string;
  role: 'initiator' | 'responder';
  state: SessionState;
  proposed_skills: string[];
  agreed_skills: string[];
  agreed_trust_tier: TrustTier;
  agreed_max_context_privacy: string;
  agreed_max_calls: number;
  call_count: number;
  tasks_completed: number;
  tasks_failed: number;
  created_at: string;
  accepted_at: string | null;
  closed_at: string | null;
  expires_at: string;
}

// ── Skill Cards ──────────────────────────────────────────

export interface SkillCard {
  skill_name: string;
  skill_version: string;
  description: string;
  provider: {
    agent_id: string;
    wallet: string;
    display_name: string;
  };
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  min_trust_tier: TrustTier;
  max_context_privacy_tier: string;
  schema_hash: string;
  tags: string[];
}

// ── Workflows ────────────────────────────────────────────

export type WorkflowState = 'draft' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled';
export type StepState = 'pending' | 'ready' | 'dispatched' | 'in_progress' | 'completed' | 'failed' | 'skipped';

export interface WorkflowStep {
  step_id: string;
  skill: string;
  target_peer: string | null;
  state: StepState;
  depends_on: string[];
  input_template: unknown;
  resolved_input: unknown;
  output: unknown;
  task_id: string | null;
  error_message: string | null;
  dispatched_at: string | null;
  completed_at: string | null;
}

export interface Workflow {
  workflow_id: string;
  name: string;
  state: WorkflowState;
  steps: WorkflowStep[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  timeout_seconds: number;
  initiator_id: string;
  error_message: string | null;
}

// ── Metering ─────────────────────────────────────────────

export interface UsageReceipt {
  receipt_id: string;
  task_id: string;
  caller: string;
  provider: string;
  skill_name: string;
  skill_version: string;
  status: 'completed' | 'failed';
  duration_ms: number;
  input_size_bytes: number;
  output_size_bytes: number;
  session_id: string | null;
  created_at: string;
}

// ── Activity ─────────────────────────────────────────────

export interface ActivityItem {
  id: string;
  type: 'message' | 'task' | 'session' | 'trust' | 'workflow';
  title: string;
  description: string;
  timestamp: string;
  icon?: string;
  peer?: string;
  status?: string;
}
