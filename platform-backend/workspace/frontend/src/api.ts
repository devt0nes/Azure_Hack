// API utility for complaint chatbot backend
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5100';

export async function submitComplaint(user_id: string, message: string) {
  try {
    const res = await fetch(`${BASE_URL}/api/complaints`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id, message }),
    });
    return await res.json();
  } catch (e: any) { return { error: e.message || 'Network error' }; }
}

export async function getComplaintStatus(complaint_id: string) {
  try {
    const res = await fetch(`${BASE_URL}/api/complaints/${complaint_id}/status`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    });
    return await res.json();
  } catch (e: any) { return { error: e.message || 'Network error' }; }
}

export async function listComplaints(user_id: string) {
  try {
    const res = await fetch(`${BASE_URL}/api/complaints?user_id=${encodeURIComponent(user_id)}`);
    return await res.json();
  } catch (e: any) { return { error: e.message || 'Network error' }; }
}

export async function chatWithAgent(complaint_id: string, sender: string, message: string) {
  try {
    const res = await fetch(`${BASE_URL}/api/complaints/${complaint_id}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sender, message }),
    });
    return await res.json();
  } catch (e: any) { return { error: e.message || 'Network error' }; }
}

export async function escalateComplaint(complaint_id: string) {
  try {
    const res = await fetch(`${BASE_URL}/api/complaints/${complaint_id}/escalate`, {
      method: 'POST',
      headers: { 'Accept': 'application/json' },
    });
    return await res.json();
  } catch (e: any) { return { error: e.message || 'Network error' }; }
}
