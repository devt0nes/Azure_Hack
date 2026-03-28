import React, { useState } from 'react';
interface Props {
  onSubmit: (message: string) => void;
  loading?: boolean;
}
export default function ComplaintForm({ onSubmit, loading }: Props) {
  const [message, setMessage] = useState('');
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!message.trim()) return;
    onSubmit(message);
    setMessage('');
  };
  return (
    <form className="mt-4 flex flex-col space-y-2" onSubmit={handleSubmit} aria-label="Complaint submission form">
      <textarea
        value={message}
        onChange={e => setMessage(e.target.value)}
        className="min-h-[100px] p-3 border rounded focus:ring-2 focus:ring-primary bg-background text-secondary"
        placeholder="Describe your issue..."
        required
        aria-required="true"
      />
      <button
        type="submit"
        className="py-2 px-4 rounded font-semibold bg-primary text-white hover:bg-secondary focus:outline-none focus:ring-2 focus:ring-primary"
        disabled={loading || message.trim().length === 0}
        aria-disabled={loading || message.trim().length === 0}
      >
        {loading ? 'Submitting...' : 'Submit Complaint'}
      </button>
    </form>
  );
}
