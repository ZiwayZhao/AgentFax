/* AgentFax API client — thin fetch wrapper */

const BASE = '';  // Same origin (Vite proxy in dev, same server in prod)

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new ApiError(res.status, text);
  }

  return res.json();
}

// ── GET helpers ──────────────────────────────────────────

export function fetchStats() {
  return request<import('../types').DashboardStats>('/api/stats');
}

export function fetchHealth() {
  return request<{ status: string }>('/api/health');
}

export function fetchAgentProfile() {
  return request<import('../types').AgentProfile>('/api/agent/profile');
}

export function fetchPeers() {
  return request<import('../types').Peer[]>('/api/peers');
}

export async function fetchTasks(params?: { state?: string; skill?: string; limit?: number }) {
  const qs = new URLSearchParams();
  if (params?.state) qs.set('state', params.state);
  if (params?.skill) qs.set('skill', params.skill);
  if (params?.limit) qs.set('limit', String(params.limit));
  const q = qs.toString();
  const res = await request<{ tasks: import('../types').Task[] }>(`/api/tasks${q ? `?${q}` : ''}`);
  return res.tasks;
}

export async function fetchMessages(params?: { type?: string; limit?: number; offset?: number }) {
  const qs = new URLSearchParams();
  if (params?.type) qs.set('type', params.type);
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.offset) qs.set('offset', String(params.offset));
  const q = qs.toString();
  const res = await request<{ messages: unknown[]; total: number }>(`/api/messages${q ? `?${q}` : ''}`);
  return res.messages;
}

export function fetchActivity(limit = 20) {
  return request<import('../types').ActivityItem[]>(`/api/activity?limit=${limit}`);
}

// ── Future endpoints (F2-F6) ─────────────────────────────

export function fetchSessions(params?: { state?: string }) {
  const qs = new URLSearchParams();
  if (params?.state) qs.set('state', params.state);
  const q = qs.toString();
  return request<import('../types').Session[]>(`/api/sessions${q ? `?${q}` : ''}`);
}

export function fetchWorkflows(params?: { state?: string }) {
  const qs = new URLSearchParams();
  if (params?.state) qs.set('state', params.state);
  const q = qs.toString();
  return request<import('../types').Workflow[]>(`/api/workflows${q ? `?${q}` : ''}`);
}

export function fetchSkillCards() {
  return request<import('../types').SkillCard[]>('/api/skill-cards');
}

export function fetchMeteringReceipts(params?: { limit?: number }) {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return request<import('../types').UsageReceipt[]>(`/api/metering/receipts${q ? `?${q}` : ''}`);
}

// ── POST/PATCH helpers ───────────────────────────────────

export function patchTrust(peerId: string, tier: number) {
  return request<{ ok: boolean }>(`/api/peers/${peerId}/trust`, {
    method: 'PATCH',
    body: JSON.stringify({ trust_tier: tier }),
  });
}

export function postSessionAction(sessionId: string, action: 'accept' | 'reject' | 'close') {
  return request<{ ok: boolean }>(`/api/sessions/${sessionId}/${action}`, {
    method: 'POST',
  });
}

export { ApiError };
