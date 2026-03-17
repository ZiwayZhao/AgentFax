import { TRUST_TIER_LABELS, TRUST_TIER_COLORS } from '../lib/constants';

interface TrustBadgeProps {
  tier: number;
}

export function TrustBadge({ tier }: TrustBadgeProps) {
  const label = TRUST_TIER_LABELS[tier] || `Tier ${tier}`;
  const color = TRUST_TIER_COLORS[tier] || 'var(--text-secondary)';

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 15%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
      }}
    >
      {label}
    </span>
  )
}
