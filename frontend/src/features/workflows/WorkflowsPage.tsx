import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchWorkflows } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/EmptyState'
import type { Workflow, WorkflowStep } from '../../lib/types'

const STATE_COLORS: Record<string, string> = {
  draft: 'var(--text-muted)',
  running: 'var(--accent-blue)',
  paused: 'var(--accent-yellow)',
  completed: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  cancelled: 'var(--text-muted)',
}

const STEP_COLORS: Record<string, string> = {
  pending: 'var(--text-muted)',
  ready: 'var(--accent-blue)',
  dispatched: 'var(--accent-yellow)',
  in_progress: 'var(--accent-yellow)',
  completed: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  skipped: 'var(--text-muted)',
}

export function WorkflowsPage() {
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: workflows, isLoading } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => fetchWorkflows(),
  })

  return (
    <div>
      <PageHeader
        title="Workflows"
        description="Multi-step task orchestration"
      />

      {isLoading ? (
        <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
      ) : workflows && workflows.length > 0 ? (
        <div className="space-y-3">
          {workflows.map(wf => (
            <WorkflowRow
              key={wf.workflow_id}
              workflow={wf}
              expanded={expanded === wf.workflow_id}
              onToggle={() => setExpanded(expanded === wf.workflow_id ? null : wf.workflow_id)}
            />
          ))}
        </div>
      ) : (
        <EmptyState title="No workflows" description="No workflows created yet" />
      )}
    </div>
  )
}

function WorkflowRow({ workflow, expanded, onToggle }: { workflow: Workflow; expanded: boolean; onToggle: () => void }) {
  const color = STATE_COLORS[workflow.state] || 'var(--text-muted)'
  const steps = workflow.steps || []
  const completedSteps = steps.filter(s => s.state === 'completed').length

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}
    >
      <button onClick={onToggle} className="w-full text-left p-4 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{workflow.name || workflow.workflow_id}</div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {completedSteps}/{steps.length} steps &middot; {new Date(workflow.created_at).toLocaleString()}
            </div>
          </div>
        </div>
        <span
          className="text-xs px-2 py-0.5 rounded capitalize flex-shrink-0"
          style={{ background: color, color: 'var(--bg-primary)' }}
        >
          {workflow.state}
        </span>
      </button>

      {expanded && steps.length > 0 && (
        <div className="px-4 pb-4 border-t" style={{ borderColor: 'var(--border)' }}>
          <div className="mt-3 space-y-2">
            {steps.map((step, i) => (
              <StepRow key={step.step_id} step={step} index={i} />
            ))}
          </div>
          {workflow.error_message && (
            <div className="mt-3 text-xs p-2 rounded" style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-red)' }}>
              {workflow.error_message}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StepRow({ step, index }: { step: WorkflowStep; index: number }) {
  const color = STEP_COLORS[step.state] || 'var(--text-muted)'
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-5 text-right" style={{ color: 'var(--text-muted)' }}>{index + 1}</span>
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
      <span className="font-medium">{step.skill}</span>
      {step.target_peer && (
        <span style={{ color: 'var(--text-muted)' }}>{step.target_peer}</span>
      )}
      <span className="capitalize" style={{ color }}>{step.state}</span>
      {step.error_message && (
        <span style={{ color: 'var(--accent-red)' }} className="truncate">{step.error_message}</span>
      )}
    </div>
  )
}
