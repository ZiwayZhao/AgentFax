import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchSkillCards } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { TrustBadge } from '../../components/TrustBadge'
import { EmptyState } from '../../components/EmptyState'
import { PRIVACY_LABELS, PRIVACY_COLORS } from '../../lib/constants'
import type { SkillCardBasic } from '../../lib/types'

export function SkillBrowserPage() {
  const [search, setSearch] = useState('')

  const { data: cards, isLoading } = useQuery({
    queryKey: ['skill-cards'],
    queryFn: fetchSkillCards,
  })

  const filtered = (cards || []).filter(card =>
    card.skill_name.toLowerCase().includes(search.toLowerCase()) ||
    card.description?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div>
      <PageHeader
        title="Skill Cards"
        description={`${cards?.length || 0} skills available across the network`}
      />

      <input
        type="text"
        placeholder="Search skills..."
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
      ) : filtered.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((card, i) => (
            <SkillCardView key={`${card._peer_id || ''}-${card.skill_name}-${i}`} card={card} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No skills"
          description={search ? 'No matching skills found' : 'No skill cards cached from peers yet'}
        />
      )}
    </div>
  )
}

function SkillCardView({ card }: { card: SkillCardBasic }) {
  const privacyTier = card.max_context_privacy_tier || 'L2_TRUSTED'
  const tags = card.tags || []

  return (
    <div
      className="rounded-lg p-4"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-sm">{card.skill_name}</span>
        <TrustBadge tier={card.min_trust_tier ?? 0} />
      </div>

      <div className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
        {card.description || 'No description'}
      </div>

      <div className="flex items-center gap-2 mb-2">
        {PRIVACY_LABELS[privacyTier] && (
          <span
            className="text-xs px-1.5 py-0.5 rounded"
            style={{
              background: PRIVACY_COLORS[privacyTier] || 'var(--bg-tertiary)',
              color: 'var(--bg-primary)',
            }}
          >
            {PRIVACY_LABELS[privacyTier]}
          </span>
        )}
        {card.skill_version && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            v{card.skill_version}
          </span>
        )}
      </div>

      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {tags.map(tag => (
            <span
              key={tag}
              className="text-xs px-1.5 py-0.5 rounded"
              style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {(card.provider || card._peer_id) && (
        <div className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
          Provider: {card.provider?.display_name || card._peer_id || 'unknown'}
        </div>
      )}
    </div>
  )
}
