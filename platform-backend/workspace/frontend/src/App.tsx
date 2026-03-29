import { Link, Route, Routes, Navigate } from 'react-router-dom';
import Register from './pages/Register';
import Login from './pages/Login';

function Home() {
  return (
    <div className="mx-auto max-w-3xl p-8">
      <h1 className="text-3xl font-heading font-bold text-primary mb-2">Welcome to Restroom Finder</h1>
      <div className="text-base text-slate-600">A community-powered map for restroom access. Please sign in or browse the map!</div>
      <div className="mt-6 flex gap-3">
        <Link to="/login" className="px-4 py-2 font-bold rounded bg-primary text-white hover:bg-secondary transition-colors">Sign In</Link>
        <Link to="/register" className="px-4 py-2 rounded border border-primary text-primary hover:bg-primary hover:text-white transition-colors">Sign Up</Link>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-background font-sans">
      <nav className="border-b bg-white shadow">
        <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-3">
          <Link to="/" className="font-heading text-xl font-bold text-primary">Restroom Finder</Link>
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}
