import { TrustTier } from './types';

export const TRUST_TIER_LABELS: Record<number, string> = {
  [TrustTier.UNTRUSTED]: 'Untrusted',
  [TrustTier.KNOWN]: 'Known',
  [TrustTier.INTERNAL]: 'Internal',
  [TrustTier.PRIVILEGED]: 'Privileged',
  [TrustTier.SYSTEM]: 'System',
};

export const TRUST_TIER_COLORS: Record<number, string> = {
  [TrustTier.UNTRUSTED]: 'var(--trust-untrusted)',
  [TrustTier.KNOWN]: 'var(--trust-known)',
  [TrustTier.INTERNAL]: 'var(--trust-internal)',
  [TrustTier.PRIVILEGED]: 'var(--trust-privileged)',
  [TrustTier.SYSTEM]: 'var(--trust-system)',
};

export const PRIVACY_LABELS: Record<string, string> = {
  L1_PUBLIC: 'Public',
  L2_TRUSTED: 'Trusted',
  L3_PRIVATE: 'Private',
};

export const PRIVACY_COLORS: Record<string, string> = {
  L1_PUBLIC: 'var(--privacy-public)',
  L2_TRUSTED: 'var(--privacy-trusted)',
  L3_PRIVATE: 'var(--privacy-private)',
};

export const SESSION_STATE_COLORS: Record<string, string> = {
  proposed: 'var(--accent-yellow)',
  active: 'var(--accent-green)',
  closing: 'var(--accent-orange)',
  closed: 'var(--text-secondary)',
  completed: 'var(--accent-blue)',
  expired: 'var(--text-muted)',
  rejected: 'var(--accent-red)',
};

export const TASK_STATE_COLORS: Record<string, string> = {
  pending: 'var(--text-secondary)',
  accepted: 'var(--accent-blue)',
  in_progress: 'var(--accent-yellow)',
  completed: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  cancelled: 'var(--text-muted)',
  timed_out: 'var(--accent-red)',
};
