import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { chatWithAgent, escalateComplaint } from '../api';

export default function ComplaintChat() {
  const { complaint_id } = useParams();
  const [messages, setMessages] = useState<Array<{ sender: string; message: string }>>([
    { sender: 'auto', message: 'Welcome to support chat. Describe your issue, and you may escalate anytime.' }
  ]);
  const [input, setInput] = useState('');
  const [reply, setReply] = useState('');
  const [escalated, setEscalated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string|null>(null);

  const handleSend = async () => {
    if (!input.trim() || !complaint_id) return;
    setLoading(true);
    const res = await chatWithAgent(complaint_id, 'user', input);
    if (res.error) setError(res.error);
    else {
      setError(null);
      setMessages([...messages, { sender: 'user', message: input }, { sender: 'auto', message: res.reply }]);
      setReply(res.reply);
      setEscalated(res.escalated);
    }
    setInput('');
    setLoading(false);
  };

  const handleEscalate = async () => {
    if (!complaint_id) return;
    setLoading(true);
    const res = await escalateComplaint(complaint_id);
    if (res.error) setError(res.error);
    else {
      setEscalated(res.escalated);
      setMessages([...messages, { sender: 'auto', message: res.message }]);
    }
    setLoading(false);
  };

  return (
    <div className="max-w-xl mx-auto py-8 px-3">
      <h2 className="text-2xl font-bold text-secondary">Complaint Chat</h2>
      <div className="mt-5 border rounded bg-background p-5 min-h-[180px]">
        <ul aria-live="polite" className="space-y-2">
          {messages.map((m, i) => (
            <li key={i} className={`rounded px-3 py-2 ${m.sender === 'user' ? 'bg-primary text-white ml-auto max-w-[75%]' : 'bg-secondary text-white mr-auto max-w-[75%]'}`}>{m.message}</li>
          ))}
        </ul>
      </div>
      <div className="mt-4 flex flex-col space-y-2">
        <textarea
          className="p-3 border rounded focus:ring-2 focus:ring-primary bg-background text-secondary min-h-[80px]"
          placeholder="Type your message..."
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={loading}
          aria-label="Chat message input"
        />
        <div className="flex items-center gap-2">
          <button
            className="py-2 px-4 rounded bg-primary text-white font-semibold hover:bg-secondary focus:outline-none focus:ring-2 focus:ring-primary"
            onClick={handleSend}
            disabled={loading || !input.trim() || escalated}
            aria-disabled={loading || !input.trim() || escalated}
          >{loading ? 'Sending...' : 'Send'}</button>
          <button
            className="py-2 px-4 rounded bg-secondary text-white font-semibold hover:bg-primary focus:outline-none focus:ring-2 focus:ring-secondary"
            onClick={handleEscalate}
            disabled={loading || escalated}
            aria-disabled={loading || escalated}
          >Escalate</button>
        </div>
      </div>
      {error && <div className="mt-4 bg-red-100 text-red-600 rounded px-3 py-2" role="alert">{error}</div>}
      {escalated && <div className="mt-3 bg-primary text-white rounded px-3 py-2">Issue has been escalated to a human agent.</div>}
    </div>
  );
}
