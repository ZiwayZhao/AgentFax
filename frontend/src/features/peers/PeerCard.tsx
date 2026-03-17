import type { Peer } from '../../lib/types'
import { StatusDot } from '../../components/StatusDot'
import { TrustBadge } from '../../components/TrustBadge'

interface PeerCardProps {
  peer: Peer
  onClick: () => void
}

export function PeerCard({ peer, onClick }: PeerCardProps) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-lg p-4 transition-colors hover:brightness-110"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <StatusDot status={peer.is_online ? 'online' : 'offline'} />
          <span className="font-medium text-sm">{peer.name}</span>
        </div>
        <TrustBadge tier={peer.trust_tier} />
      </div>

      <div className="flex items-center justify-between text-xs" style={{ color: 'var(--text-muted)' }}>
        <span>
          {peer.skills.length > 0 ? `${peer.skills.length} skill${peer.skills.length !== 1 ? 's' : ''}` : 'No skills'}
        </span>
        {peer.latency_ms != null && <span>{peer.latency_ms.toFixed(0)}ms</span>}
      </div>

      {peer.skills.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {peer.skills.slice(0, 4).map(skill => (
            <span
              key={skill}
              className="text-xs px-1.5 py-0.5 rounded"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
            >
              {skill}
            </span>
          ))}
          {peer.skills.length > 4 && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              +{peer.skills.length - 4}
            </span>
          )}
        </div>
      )}
    </button>
  )
}
