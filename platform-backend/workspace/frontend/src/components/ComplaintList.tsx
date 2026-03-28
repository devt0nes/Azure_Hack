import React from 'react';
import { Link } from 'react-router-dom';
interface Complaint {
  complaint_id: string;
  status: string;
  category: string;
  updated_at: string;
}
interface Props {
  complaints: Complaint[];
  loading: boolean;
}
export default function ComplaintList({ complaints, loading }: Props) {
  if (loading) return <div className="mt-4 text-primary">Loading...</div>;
  if (!complaints || complaints.length === 0)
    return <div className="mt-4 text-secondary">No complaints found.</div>;
  return (
    <ul className="mt-4 space-y-3" aria-label="Complaint list">
      {complaints.map(c => (
        <li key={c.complaint_id} className="border rounded p-3 bg-background">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between">
            <div>
              <span className="font-semibold text-primary">{c.category}</span>
              <span className="ml-2 text-secondary">[{c.status}]</span>
            </div>
            <Link
              to={`/complaint/${c.complaint_id}/status`}
              className="mt-2 sm:mt-0 font-medium text-primary underline focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label={`View status of complaint ${c.complaint_id}`}
            >
              View Status
            </Link>
            <Link
              to={`/complaint/${c.complaint_id}/chat`}
              className="mt-2 sm:mt-0 font-medium text-primary underline focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label={`Chat about complaint ${c.complaint_id}`}
            >
              Chat
            </Link>
          </div>
          <div className="mt-2 text-xs text-secondary">Updated: {new Date(c.updated_at).toLocaleString()}</div>
        </li>
      ))}
    </ul>
  );
}
