import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchPeers } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/EmptyState'
import { PeerCard } from './PeerCard'
import { PeerDrawer } from './PeerDrawer'

export function PeersPage() {
  const [selectedPeer, setSelectedPeer] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const { data: peers, isLoading } = useQuery({
    queryKey: ['peers'],
    queryFn: fetchPeers,
  })

  const filtered = (peers || []).filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  )

  const online = filtered.filter(p => p.is_online)
  const offline = filtered.filter(p => !p.is_online)
  const sorted = [...online, ...offline]

  return (
    <div>
      <PageHeader
        title="Peers"
        description={`${peers?.filter(p => p.is_online).length || 0} online, ${peers?.length || 0} total`}
      />

      <input
        type="text"
        placeholder="Search peers..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm px-3 py-2 rounded-lg text-sm mb-4"
        style={{
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          color: 'var(--text-primary)',
        }}
      />

      {isLoading ? (
        <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      ) : sorted.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sorted.map(peer => (
            <PeerCard
              key={peer.name}
              peer={peer}
              onClick={() => setSelectedPeer(peer.name)}
            />
          ))}
        </div>
      ) : (
        <EmptyState title="No peers" description="No agents discovered yet" />
      )}

      {selectedPeer && (
        <PeerDrawer
          peerId={selectedPeer}
          onClose={() => setSelectedPeer(null)}
        />
      )}
    </div>
  )
}
