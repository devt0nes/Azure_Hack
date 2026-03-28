import React from 'react';
interface Props { status: string; }
export default function StatusBadge({ status }: Props) {
  let color = 'bg-secondary';
  if (status === 'open') color = 'bg-primary';
  else if (status === 'resolved') color = 'bg-green-600';
  else if (status === 'escalated') color = 'bg-yellow-500';
  return <span className={`inline-block rounded px-2 py-1 text-xs text-white ${color}`}>{status}</span>;
}
