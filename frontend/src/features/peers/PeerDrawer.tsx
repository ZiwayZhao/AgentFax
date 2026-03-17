import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchPeerDetail, patchTrust } from '../../lib/api/client'
import { StatusDot } from '../../components/StatusDot'
import { TrustBadge } from '../../components/TrustBadge'
import { TRUST_TIER_LABELS, TRUST_TIER_COLORS } from '../../lib/constants'
import { TrustTier } from '../../lib/types'

interface PeerDrawerProps {
  peerId: string
  onClose: () => void
}

const TRUST_TIERS = [
  TrustTier.UNTRUSTED,
  TrustTier.KNOWN,
  TrustTier.INTERNAL,
  TrustTier.PRIVILEGED,
] as const

export function PeerDrawer({ peerId, onClose }: PeerDrawerProps) {
  const queryClient = useQueryClient()
  const { data: peer, isLoading } = useQuery({
    queryKey: ['peer-detail', peerId],
    queryFn: () => fetchPeerDetail(peerId),
  })

  const trustMutation = useMutation({
    mutationFn: (tier: number) => patchTrust(peerId, tier),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['peer-detail', peerId] })
      queryClient.invalidateQueries({ queryKey: ['peers'] })
    },
  })

  const rep = peer?.reputation ?? {}

  return (
    <div
      className="fixed inset-0 z-50 flex"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="flex-1" style={{ background: 'rgba(0,0,0,0.5)' }} />

      <div
        className="w-full max-w-md overflow-y-auto p-6"
        style={{ background: 'var(--bg-primary)', borderLeft: '1px solid var(--border)' }}
      >
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-bold">{peerId}</h2>
          <button
            onClick={onClose}
            className="text-sm px-2 py-1 rounded"
            style={{ color: 'var(--text-muted)' }}
          >
            Close
          </button>
        </div>

        {isLoading ? (
          <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
        ) : !peer || peer.error ? (
          <div className="text-sm" style={{ color: 'var(--accent-red)' }}>{peer?.error || 'Not found'}</div>
        ) : (
          <div className="space-y-6">
            <div className="flex items-center gap-3">
              <StatusDot status={peer.is_online ? 'online' : 'offline'} size={12} />
              <span className="text-sm">{peer.is_online ? 'Online' : 'Offline'}</span>
              {peer.latency_ms != null && (
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {peer.latency_ms.toFixed(0)}ms latency
                </span>
              )}
            </div>

            <div>
              <h3 className="text-xs font-semibold mb-2" style={{ color: 'var(--text-secondary)' }}>
                Trust Level
              </h3>
              <div className="flex gap-1">
                {TRUST_TIERS.map(tier => {
                  const active = peer.trust_tier === tier
                  return (
                    <button
                      key={tier}
                      onClick={() => trustMutation.mutate(tier)}
                      disabled={trustMutation.isPending}
                      className="px-3 py-1.5 text-xs rounded transition-colors"
                      style={{
                        background: active ? TRUST_TIER_COLORS[tier] : 'var(--bg-tertiary)',
                        color: active ? 'var(--bg-primary)' : 'var(--text-muted)',
                        opacity: trustMutation.isPending ? 0.6 : 1,
                      }}
                    >
                      {TRUST_TIER_LABELS[tier]}
                    </button>
                  )
                })}
              </div>
            </div>

            <div>
              <h3 className="text-xs font-semibold mb-2" style={{ color: 'var(--text-secondary)' }}>
                Reputation
              </h3>
              <div className="grid grid-cols-2 gap-3">
                <RepStat label="Success Rate" value={
                  rep.success_rate != null ? `${(rep.success_rate * 100).toFixed(0)}%` : 'N/A'
                } />
                <RepStat label="Interactions" value={rep.total_interactions ?? 0} />
                <RepStat label="Successes" value={rep.successes ?? 0} />
                <RepStat label="Failures" value={rep.failures ?? 0} />
                <RepStat label="Avg Latency" value={
                  rep.avg_latency_ms != null ? `${rep.avg_latency_ms.toFixed(0)}ms` : 'N/A'
                } />
                <RepStat label="First Seen" value={
                  rep.first_seen ? new Date(rep.first_seen).toLocaleDateString() : 'N/A'
                } />
              </div>
            </div>

            {peer.skill_cards.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold mb-2" style={{ color: 'var(--text-secondary)' }}>
                  Skills ({peer.skill_cards.length})
                </h3>
                <div className="space-y-2">
                  {peer.skill_cards.map(card => (
                    <div
                      key={card.skill_name}
                      className="rounded-lg p-3 text-sm"
                      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium">{card.skill_name}</span>
                        <TrustBadge tier={card.min_trust_tier ?? 0} />
                      </div>
                      {card.description && (
                        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                          {card.description}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {peer.wallet && (
              <div>
                <h3 className="text-xs font-semibold mb-1" style={{ color: 'var(--text-secondary)' }}>
                  Wallet
                </h3>
                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                  {peer.wallet}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function RepStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded p-2" style={{ background: 'var(--bg-secondary)' }}>
      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-sm font-medium">{value}</div>
    </div>
  )
}
