import { renderAuth } from './components/auth.js';
import { renderDashboard } from './components/dashboard.js';
import { checkAuthState } from './utils/auth.js';

const app = document.getElementById('app');

// Initialize the application
const init = async () => {
  const isAuthenticated = await checkAuthState();
  if (isAuthenticated) {
    renderDashboard(app);
  } else {
    renderAuth(app);
  }
};

init();