const LEVELS = [
  {
    value: 0 as const,
    label: 'Manual',
    description: 'Never share context automatically. Ask approval for every request.',
    color: 'var(--accent-red)',
  },
  {
    value: 1 as const,
    label: 'Ask First',
    description: 'Share public context automatically, ask for trusted/private data.',
    color: 'var(--accent-yellow)',
  },
  {
    value: 2 as const,
    label: 'Auto',
    description: 'Share context based on trust tiers. Only private data requires approval.',
    color: 'var(--accent-green)',
  },
]

interface AutonomyDialProps {
  level: 0 | 1 | 2
  onChange: (level: 0 | 1 | 2) => void
  saving?: boolean
}

export function AutonomyDial({ level, onChange, saving }: AutonomyDialProps) {
  return (
    <div
      className="rounded-lg p-5"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <h2 className="text-sm font-semibold mb-4" style={{ color: 'var(--text-secondary)' }}>
        Autonomy Level
      </h2>

      <div className="space-y-3">
        {LEVELS.map(opt => {
          const active = level === opt.value
          return (
            <button
              key={opt.value}
              onClick={() => onChange(opt.value)}
              disabled={saving}
              className="w-full text-left rounded-lg p-4 transition-all"
              style={{
                background: active ? 'var(--bg-tertiary)' : 'transparent',
                border: active ? `2px solid ${opt.color}` : '2px solid transparent',
                opacity: saving ? 0.6 : 1,
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ background: active ? opt.color : 'var(--text-muted)' }}
                />
                <span className="text-sm font-medium">{opt.label}</span>
                {active && (
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: opt.color, color: 'var(--bg-primary)' }}>
                    Active
                  </span>
                )}
              </div>
              <p className="text-xs ml-5" style={{ color: 'var(--text-muted)' }}>
                {opt.description}
              </p>
            </button>
          )
        })}
      </div>

      {saving && (
        <div className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>Saving...</div>
      )}
    </div>
  )
}
