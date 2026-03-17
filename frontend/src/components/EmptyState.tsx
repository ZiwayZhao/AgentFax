interface EmptyStateProps {
  title: string;
  description?: string;
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div
      className="flex flex-col items-center justify-center py-16 rounded-lg"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <div className="text-lg font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
        {title}
      </div>
      {description && (
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {description}
        </div>
      )}
    </div>
  )
}
