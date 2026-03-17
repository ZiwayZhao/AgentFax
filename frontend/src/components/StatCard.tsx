interface StatCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
  color?: string;
}

export function StatCard({ label, value, sublabel, color }: StatCardProps) {
  return (
    <div
      className="rounded-lg p-4"
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
      }}
    >
      <div className="text-xs mb-1" style={{ color: 'var(--text-secondary)' }}>
        {label}
      </div>
      <div
        className="text-2xl font-bold"
        style={{ color: color || 'var(--text-primary)' }}
      >
        {value}
      </div>
      {sublabel && (
        <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
          {sublabel}
        </div>
      )}
    </div>
  )
}
