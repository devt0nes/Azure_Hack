import { Link, Route, Routes } from 'react-router-dom';
import ComplaintEntry from './pages/ComplaintEntry';
import ComplaintStatus from './pages/ComplaintStatus';
import ComplaintChat from './pages/ComplaintChat';

export default function App() {
  return (
    <div className="min-h-screen bg-background text-secondary">
      <nav className="border-b bg-white" role="navigation">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3">
          <Link to="/" className="font-semibold text-primary">Home</Link>
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<ComplaintEntry />} />
        <Route path="/complaint/:complaint_id/status" element={<ComplaintStatus />} />
        <Route path="/complaint/:complaint_id/chat" element={<ComplaintChat />} />
      </Routes>
    </div>
  );
}
