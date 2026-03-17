import { PRIVACY_LABELS, PRIVACY_COLORS } from '../../lib/constants'
import type { ContextPolicy, ContextPolicyUpdate } from '../../lib/api/client'

interface ContextPolicyEditorProps {
  policy: Partial<ContextPolicy>
  onUpdate: (update: ContextPolicyUpdate) => void
  saving?: boolean
}

const CATEGORIES = ['general', 'project', 'credentials', 'personal', 'system']
const PRIVACY_OPTIONS = ['L1_PUBLIC', 'L2_TRUSTED', 'L3_PRIVATE'] as const

export function ContextPolicyEditor({ policy, onUpdate, saving }: ContextPolicyEditorProps) {
  const categoryPolicies = policy.category_policies || {}

  function handleChange(category: string, privacyTier: string) {
    onUpdate({
      category_policies: { ...categoryPolicies, [category]: privacyTier },
    })
  }

  return (
    <div
      className="rounded-lg p-5"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <h2 className="text-sm font-semibold mb-1" style={{ color: 'var(--text-secondary)' }}>
        Context Sharing Policy
      </h2>
      <p className="text-xs mb-4" style={{ color: 'var(--text-muted)' }}>
        Set the default privacy tier for each context category
      </p>

      <div className="space-y-3">
        {CATEGORIES.map(cat => {
          const current = categoryPolicies[cat] || 'L2_TRUSTED'
          return (
            <div key={cat} className="flex items-center justify-between">
              <span className="text-sm capitalize">{cat}</span>
              <div className="flex gap-1">
                {PRIVACY_OPTIONS.map(opt => {
                  const active = current === opt
                  return (
                    <button
                      key={opt}
                      onClick={() => handleChange(cat, opt)}
                      disabled={saving}
                      className="px-2 py-1 text-xs rounded transition-colors"
                      style={{
                        background: active ? PRIVACY_COLORS[opt] : 'var(--bg-tertiary)',
                        color: active ? 'var(--bg-primary)' : 'var(--text-muted)',
                        opacity: saving ? 0.6 : 1,
                      }}
                    >
                      {PRIVACY_LABELS[opt]}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
