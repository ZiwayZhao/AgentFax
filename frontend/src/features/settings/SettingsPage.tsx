import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchContextPolicy, patchContextPolicy, type ContextPolicyUpdate } from '../../lib/api/client'
import { PageHeader } from '../../components/PageHeader'
import { AutonomyDial } from './AutonomyDial'
import { ContextPolicyEditor } from './ContextPolicyEditor'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const { data: policy, isLoading } = useQuery({
    queryKey: ['context-policy'],
    queryFn: fetchContextPolicy,
  })

  const mutation = useMutation({
    mutationFn: (update: ContextPolicyUpdate) => patchContextPolicy(update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['context-policy'] })
    },
  })

  if (isLoading) {
    return (
      <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>Loading...</div>
    )
  }

  const autonomyLevel = (policy?.autonomy_level ?? 1) as 0 | 1 | 2

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Control how your agent shares context and operates autonomously"
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <AutonomyDial
          level={autonomyLevel}
          onChange={(level) => mutation.mutate({ autonomy_level: level })}
          saving={mutation.isPending}
        />
        <ContextPolicyEditor
          policy={policy ?? {}}
          onUpdate={(update) => mutation.mutate(update)}
          saving={mutation.isPending}
        />
      </div>
    </div>
  )
}
