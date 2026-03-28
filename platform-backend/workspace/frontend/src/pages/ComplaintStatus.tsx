import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getComplaintStatus } from '../api';

export default function ComplaintStatus() {
  const { complaint_id } = useParams();
  const [status, setStatus] = useState('');
  const [updatedAt, setUpdatedAt] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string|null>(null);

  useEffect(() => {
    if (!complaint_id) return;
    setLoading(true);
    getComplaintStatus(complaint_id)
      .then(res => {
        if (res.error) setError(res.error);
        else {
          setError(null);
          setStatus(res.status);
          setUpdatedAt(res.updated_at);
        }
      })
      .finally(() => setLoading(false));
  }, [complaint_id]);

  return (
    <div className="max-w-xl mx-auto py-8 px-3">
      <h2 className="text-2xl font-bold text-secondary">Complaint Status</h2>
      {loading && <div className="text-primary mt-4">Loading...</div>}
      {error && <div className="mt-4 bg-red-100 text-red-600 rounded px-3 py-2" role="alert">{error}</div>}
      {!loading && !error && (
        <div className="mt-6 border rounded bg-background p-5">
          <div className="text-lg text-primary font-medium">Status: {status}</div>
          <div className="mt-2 text-secondary text-sm">Updated: {new Date(updatedAt).toLocaleString()}</div>
        </div>
      )}
    </div>
  );
}
