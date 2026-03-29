import React, { useState } from 'react';
import { registerUser } from '../api';

export default function Register() {
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    setSuccess(false);
    try {
      const result = await registerUser(form);
      if(result.error) setError(result.error);
      else setSuccess(true);
    } catch (err: any) {
      setError(err?.message || 'Unexpected error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[80vh] flex flex-col items-center justify-center bg-background">
      <form onSubmit={handleSubmit} className="bg-white rounded shadow-lg p-8 w-full max-w-md space-y-6">
        <h1 className="text-2xl font-heading font-bold text-primary">Create Account</h1>
        {error && <div className="text-red-500" role="alert">{error}</div>}
        {success && <div className="text-green-600">Registration successful! You may login.</div>}
        <div>
          <label className="block" htmlFor="username">Username</label>
          <input id="username" name="username" type="text" className="mt-1 input input-bordered w-full" required autoComplete="username"
            value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} />
        </div>
        <div>
          <label className="block" htmlFor="email">Email</label>
          <input id="email" name="email" type="email" className="mt-1 input input-bordered w-full" required autoComplete="email"
            value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
        </div>
        <div>
          <label className="block" htmlFor="password">Password</label>
          <input id="password" name="password" type="password" className="mt-1 input input-bordered w-full" required autoComplete="new-password"
            value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
        </div>
        <button className="w-full py-2 px-4 font-bold rounded bg-primary text-white hover:bg-secondary transition-colors disabled:opacity-60" disabled={loading}>{loading ? "Creating..." : "Sign Up"}</button>
      </form>
    </div>
  );
}
