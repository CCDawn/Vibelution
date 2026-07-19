const styles = {
  empty:
    "empty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  workflowSourceCollectionAssignmentActive:
    "workflowSourceCollectionAssignmentActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  workflowSourceCollectionAssignments:
    "workflowSourceCollectionAssignments min-w-0 grid content-start justify-start gap-1.5 grid-cols-[repeat(auto-fit,minmax(9rem,max-content))] max-[640px]:grid-cols-[minmax(0,1fr)] [&_[data-vui=native-button]]:grid [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]]:min-w-0 [&_[data-vui=native-button]]:justify-items-start [&_[data-vui=native-button]]:gap-0.5 [&_[data-vui=native-button]]:text-left max-[640px]:[&_[data-vui=native-button]]:w-full [&_[data-vui=native-button]_strong]:min-w-0 [&_[data-vui=native-button]_strong]:max-w-full [&_[data-vui=native-button]_strong]:truncate [&_[data-vui=native-button]_span]:min-w-0 [&_[data-vui=native-button]_span]:max-w-full [&_[data-vui=native-button]_span]:break-words",
  workflowSourceCollectionDetails:
    "workflowSourceCollectionDetails min-w-0",
  workflowSourceCollectionQueries:
    "workflowSourceCollectionQueries min-w-0 grid content-start gap-1.5 [&>span]:grid [&>span]:min-w-0 [&>span]:gap-0.5 [&_strong]:min-w-0 [&_strong]:truncate [&_small]:min-w-0 [&_small]:break-words",
  workflowSourceCollectionRuns:
    "workflowSourceCollectionRuns min-w-0",
} as const;

export default styles;
