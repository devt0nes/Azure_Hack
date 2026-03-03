export const renderDashboard = (app) => {
  app.innerHTML = `
    <header>
      <h1>Agentic Nexus Dashboard</h1>
    </header>
    <div>
      <button id="logoutButton">Logout</button>
    </div>
  `;

  const logoutButton = document.getElementById('logoutButton');

  logoutButton.addEventListener('click', () => {
    localStorage.removeItem('authToken');
    window.location.reload();
  });
};