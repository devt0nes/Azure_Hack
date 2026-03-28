import React, { useState, useEffect } from 'react';
import { submitComplaint, listComplaints } from '../api';
import ComplaintList from '../components/ComplaintList';
import ComplaintForm from '../components/ComplaintForm';

// minimalist page for complaint submission & viewing
export default function ComplaintEntry() {
  // TODO: Replace static user_id with actual auth/session
  const user_id = 'abc-123';
  const [complaints, setComplaints] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string|null>(null);

  useEffect(() => {
    setLoading(true);
    listComplaints(user_id)
      .then(res => setComplaints(res.complaints || []))
      .catch(() => setComplaints([]))
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async (message: string) => {
    setLoading(true);
    const res = await submitComplaint(user_id, message);
    if (res.error) setError(res.error);
    else {
      setError(null);
      setComplaints([...(complaints || []), {
        complaint_id: res.complaint_id,
        status: res.status,
        category: res.category,
        updated_at: new Date().toISOString(), // not contract, but UX
      }]);
    }
    setLoading(false);
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4">
      <h2 className="text-2xl font-bold text-secondary">Submit a Complaint</h2>
      <ComplaintForm onSubmit={handleSubmit} loading={loading} />
      {error && <div role="alert" className="mt-4 bg-red-100 text-red-600 rounded px-3 py-2">{error}</div>}
      <h3 className="mt-8 text-xl text-primary font-semibold">Your Complaints</h3>
      <ComplaintList complaints={complaints} loading={loading} />
    </div>
  );
}
