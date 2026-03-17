interface StatusDotProps {
  status: 'online' | 'offline' | 'warning' | 'error';
  size?: number;
  pulse?: boolean;
}

const COLORS: Record<string, string> = {
  online: 'var(--accent-green)',
  offline: 'var(--text-muted)',
  warning: 'var(--accent-yellow)',
  error: 'var(--accent-red)',
}

export function StatusDot({ status, size = 8, pulse = true }: StatusDotProps) {
  return (
    <span
      className="inline-block rounded-full"
      style={{
        width: size,
        height: size,
        background: COLORS[status] || COLORS.offline,
        animation: pulse && status === 'online' ? 'pulse 2s infinite' : undefined,
      }}
    />
  )
}
