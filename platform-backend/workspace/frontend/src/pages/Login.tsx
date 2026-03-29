import React, { useState } from 'react';
import { loginUser } from '../api';

export default function Login() {
  const [form, setForm] = useState({ email: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess(false);
    try {
      const result = await loginUser(form);
      if(result.error) setError(result.error);
      else {
        setSuccess(true);
        // TODO: Store JWT, redirect to map/dashboard
      }
    } catch (err: any) {
      setError(err?.message || 'Unexpected error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center bg-background">
      <form onSubmit={handleSubmit} className="bg-white rounded shadow-lg p-8 w-full max-w-md space-y-6">
        <h1 className="text-2xl font-heading font-bold text-primary">Sign In</h1>
        {error && <div className="text-red-500" role="alert">{error}</div>}
        {success && <div className="text-green-600">Login successful!</div>}
        <div>
          <label className="block" htmlFor="email">Email</label>
          <input id="email" name="email" type="email" className="mt-1 input input-bordered w-full" required autoComplete="email"
            value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
        </div>
        <div>
          <label className="block" htmlFor="password">Password</label>
          <input id="password" name="password" type="password" className="mt-1 input input-bordered w-full" required autoComplete="current-password"
            value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
        </div>
        <button className="w-full py-2 px-4 font-bold rounded bg-primary text-white hover:bg-secondary transition-colors disabled:opacity-60" disabled={loading}>{loading ? "Signing in..." : "Sign In"}</button>
      </form>
    </div>
  );
}
