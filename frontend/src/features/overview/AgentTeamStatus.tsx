import type { Peer } from '../../lib/types'
import { StatusDot } from '../../components/StatusDot'
import { TrustBadge } from '../../components/TrustBadge'

interface AgentTeamStatusProps {
  peers: Peer[]
}

export function AgentTeamStatus({ peers }: AgentTeamStatusProps) {
  const online = peers.filter(p => p.is_online)
  const offline = peers.filter(p => !p.is_online)
  const sorted = [...online, ...offline]

  return (
    <div
      className="rounded-lg p-4"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold" style={{ color: 'var(--text-secondary)' }}>
          Agent Network
        </h2>
        <span className="text-xs" style={{ color: 'var(--accent-green)' }}>
          {online.length} online
        </span>
      </div>

      {sorted.length > 0 ? (
        <div className="space-y-2">
          {sorted.slice(0, 10).map(peer => (
            <div key={peer.name} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <StatusDot status={peer.is_online ? 'online' : 'offline'} />
                <span className="truncate">{peer.name}</span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <TrustBadge tier={peer.trust_tier} />
                {peer.skills.length > 0 && (
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {peer.skills.length} skill{peer.skills.length !== 1 ? 's' : ''}
                  </span>
                )}
                {peer.latency_ms != null && (
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {peer.latency_ms.toFixed(0)}ms
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
          No agents discovered yet
        </div>
      )}
    </div>
  )
}
