import { useQuery } from '@tanstack/react-query'
import { fetchStats, fetchActivity, fetchPeers, fetchSessions, fetchTasks } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { StatCard } from '../../components/StatCard'
import { EmptyState } from '../../components/EmptyState'
import { AttentionQueue } from './AttentionQueue'
import { AgentTeamStatus } from './AgentTeamStatus'

export function OverviewPage() {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: fetchStats,
  })

  const { data: activity } = useQuery({
    queryKey: ['activity'],
    queryFn: () => fetchActivity(10),
  })

  const { data: peers } = useQuery({
    queryKey: ['peers'],
    queryFn: fetchPeers,
  })

  const { data: sessions } = useQuery({
    queryKey: ['sessions-proposed'],
    queryFn: () => fetchSessions({ state: 'proposed' }),
  })

  const { data: failedTaskList } = useQuery({
    queryKey: ['tasks-failed'],
    queryFn: () => fetchTasks({ state: 'failed', limit: 10 }),
  })

  if (statsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      </div>
    )
  }

  const onlinePeers = peers?.filter(p => p.is_online) || []
  const taskStates = stats?.task_states || {}
  const completedTasks = taskStates['completed'] || 0
  const failedCount = taskStates['failed'] || 0
  const inProgress = taskStates['in_progress'] || 0

  return (
    <div>
      <PageHeader
        title="Overview"
        description="Agent collaboration status at a glance"
      />

      {/* Attention Queue */}
      <AttentionQueue
        pendingSessions={sessions || []}
        failedTasks={failedTaskList || []}
      />

      {/* KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6">
        <StatCard
          label="Peers Online"
          value={onlinePeers.length}
          sublabel={`${peers?.length || 0} total`}
          color="var(--accent-green)"
        />
        <StatCard
          label="Tasks Completed"
          value={completedTasks}
          color="var(--accent-blue)"
        />
        <StatCard
          label="Tasks In Progress"
          value={inProgress}
          color="var(--accent-yellow)"
        />
        <StatCard
          label="Tasks Failed"
          value={failedCount}
          color={failedCount > 0 ? 'var(--accent-red)' : undefined}
        />
        <StatCard
          label="Inbox"
          value={stats?.inbox_count || 0}
        />
        <StatCard
          label="Outbox"
          value={stats?.outbox_count || 0}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Agent Network */}
        <AgentTeamStatus peers={peers || []} />

        {/* Message Types */}
        <div
          className="rounded-lg p-4"
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
        >
          <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>
            Message Types
          </h2>
          {stats?.message_types && Object.keys(stats.message_types).length > 0 ? (
            <div className="space-y-1.5">
              {Object.entries(stats.message_types)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 10)
                .map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between text-sm">
                    <span className="font-mono text-xs">{type}</span>
                    <span style={{ color: 'var(--accent-blue)' }}>{count}</span>
                  </div>
                ))}
            </div>
          ) : (
            <EmptyState title="No messages" description="No messages exchanged yet" />
          )}
        </div>

        {/* Activity Feed */}
        <div
          className="rounded-lg p-4"
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
        >
          <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>
            Recent Activity
          </h2>
          {activity && activity.length > 0 ? (
            <div className="space-y-2">
              {activity.slice(0, 10).map((item) => (
                <div key={item.id || item.timestamp} className="text-sm">
                  <div className="flex items-center gap-1.5">
                    <span
                      className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      style={{
                        background:
                          item.type === 'task'
                            ? 'var(--accent-blue)'
                            : item.type === 'session'
                            ? 'var(--accent-green)'
                            : 'var(--text-muted)',
                      }}
                    />
                    <span className="truncate">{item.title || item.description}</span>
                  </div>
                  <div className="text-xs ml-3" style={{ color: 'var(--text-muted)' }}>
                    {new Date(item.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No activity" description="Waiting for first event" />
          )}
        </div>
      </div>
    </div>
  )
}
