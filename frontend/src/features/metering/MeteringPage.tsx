import { useQuery } from '@tanstack/react-query'
import { fetchMeteringReceipts } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { StatCard } from '../../components/StatCard'
import { EmptyState } from '../../components/EmptyState'
import type { UsageReceipt } from '../../lib/types'

export function MeteringPage() {
  const { data: receipts, isLoading } = useQuery({
    queryKey: ['metering-receipts'],
    queryFn: () => fetchMeteringReceipts({ limit: 100 }),
  })

  const allReceipts = receipts || []
  const completed = allReceipts.filter(r => r.status === 'completed')
  const failed = allReceipts.filter(r => r.status === 'failed')
  const totalDuration = completed.reduce((sum, r) => sum + (r.duration_ms || 0), 0)
  const avgDuration = completed.length > 0 ? totalDuration / completed.length : 0

  // Group by skill
  const bySkill: Record<string, number> = {}
  for (const r of allReceipts) {
    bySkill[r.skill_name] = (bySkill[r.skill_name] || 0) + 1
  }

  // Group by provider
  const byProvider: Record<string, number> = {}
  for (const r of allReceipts) {
    byProvider[r.provider] = (byProvider[r.provider] || 0) + 1
  }

  return (
    <div>
      <PageHeader
        title="Metering"
        description="Usage receipts and resource tracking"
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Receipts" value={allReceipts.length} color="var(--accent-blue)" />
        <StatCard label="Completed" value={completed.length} color="var(--accent-green)" />
        <StatCard label="Failed" value={failed.length} color={failed.length > 0 ? 'var(--accent-red)' : undefined} />
        <StatCard label="Avg Duration" value={avgDuration > 0 ? `${avgDuration.toFixed(0)}ms` : 'N/A'} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* By Skill */}
        <div className="rounded-lg p-4" style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>By Skill</h3>
          {Object.keys(bySkill).length > 0 ? (
            <div className="space-y-1.5">
              {Object.entries(bySkill).sort(([, a], [, b]) => b - a).map(([skill, count]) => (
                <div key={skill} className="flex items-center justify-between text-xs">
                  <span className="font-mono">{skill}</span>
                  <span style={{ color: 'var(--accent-blue)' }}>{count}</span>
                </div>
              ))}
            </div>
          ) : <div className="text-xs" style={{ color: 'var(--text-muted)' }}>No data</div>}
        </div>

        {/* By Provider */}
        <div className="rounded-lg p-4" style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
          <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>By Provider</h3>
          {Object.keys(byProvider).length > 0 ? (
            <div className="space-y-1.5">
              {Object.entries(byProvider).sort(([, a], [, b]) => b - a).map(([provider, count]) => (
                <div key={provider} className="flex items-center justify-between text-xs">
                  <span className="truncate mr-2">{provider}</span>
                  <span style={{ color: 'var(--accent-blue)' }}>{count}</span>
                </div>
              ))}
            </div>
          ) : <div className="text-xs" style={{ color: 'var(--text-muted)' }}>No data</div>}
        </div>
      </div>

      {/* Receipt table */}
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>Recent Receipts</h3>
      {isLoading ? (
        <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      ) : allReceipts.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="text-left py-2 px-2">Skill</th>
                <th className="text-left py-2 px-2">Provider</th>
                <th className="text-left py-2 px-2">Status</th>
                <th className="text-right py-2 px-2">Duration</th>
                <th className="text-right py-2 px-2">Size</th>
                <th className="text-left py-2 px-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {allReceipts.slice(0, 50).map(r => (
                <ReceiptRow key={r.receipt_id} receipt={r} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState title="No receipts" description="No usage receipts recorded yet" />
      )}
    </div>
  )
}

function ReceiptRow({ receipt }: { receipt: UsageReceipt }) {
  const statusColor = receipt.status === 'completed' ? 'var(--accent-green)' : 'var(--accent-red)'
  const totalSize = (receipt.input_size_bytes || 0) + (receipt.output_size_bytes || 0)
  const sizeStr = totalSize > 1024 ? `${(totalSize / 1024).toFixed(1)}KB` : `${totalSize}B`

  return (
    <tr className="border-t" style={{ borderColor: 'var(--border)' }}>
      <td className="py-2 px-2 font-mono">{receipt.skill_name}</td>
      <td className="py-2 px-2 truncate max-w-[120px]">{receipt.provider}</td>
      <td className="py-2 px-2">
        <span style={{ color: statusColor }}>{receipt.status}</span>
      </td>
      <td className="py-2 px-2 text-right">{receipt.duration_ms}ms</td>
      <td className="py-2 px-2 text-right">{sizeStr}</td>
      <td className="py-2 px-2" style={{ color: 'var(--text-muted)' }}>
        {new Date(receipt.created_at).toLocaleString()}
      </td>
    </tr>
  )
}
