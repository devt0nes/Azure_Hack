// Central API utility: All API calls route through here to ensure exact contract compliance.
// Uses import.meta.env for BASE_URL, falling back to localhost if unset.
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5100';

// --- Auth Endpoints ---
export async function registerUser(data: { username: string, email: string, password: string }) {
  const res = await fetch(`${BASE_URL}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function loginUser(data: { email: string, password: string }) {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

// --- Facility ---
export async function getFacilities(params?: { amenities?: string, rating?: number, open?: boolean, accessible?: boolean }) {
  // Filter query construction
  let query = '';
  if (params) {
    const qp = Object.entries(params)
      .filter(([_, v]) => v !== undefined && v !== '')
      .map(([k, v]) => encodeURIComponent(k)+"="+encodeURIComponent(v));
    if (qp.length) query = '?' + qp.join('&');
  }
  const res = await fetch(`${BASE_URL}/api/facilities${query}`);
  return res.json();
}

export async function getFacilityDetails(id: string) {
  const res = await fetch(`${BASE_URL}/api/facilities/${id}`);
  return res.json();
}

export async function submitReview(facilityId: string, data: { rating: number, review: string }) {
  const res = await fetch(`${BASE_URL}/api/facilities/${facilityId}/reviews`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function addFacility(data: { name: string, description: string, latitude: number, longitude: number, amenities: string[], accessible: boolean }) {
  const res = await fetch(`${BASE_URL}/api/facilities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return res.json();
}

export async function updateFacilityStatus(id: string, status: string) {
  const res = await fetch(`${BASE_URL}/api/facilities/${id}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({status})
  });
  return res.json();
}

// --- Notifications ---
export async function getNotifications() {
  const res = await fetch(`${BASE_URL}/api/notifications`);
  return res.json();
}
// --- Dashboard/Admin ---
export async function getDashboardStats() {
  const res = await fetch(`${BASE_URL}/api/admin/dashboard`);
  return res.json();
}

export async function moderateReview(id: string, status: string) {
  const res = await fetch(`${BASE_URL}/api/admin/review/${id}/moderate`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({status})
  });
  return res.json();
}
