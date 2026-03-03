import { loginUser } from '../services/api.js';

export const renderAuth = (app) => {
  app.innerHTML = `
    <header>
      <h1>Welcome to Agentic Nexus</h1>
    </header>
    <form id="loginForm">
      <input type="email" id="email" placeholder="Email" required />
      <input type="password" id="password" placeholder="Password" required />
      <button type="submit">Login</button>
    </form>
    <p id="errorMessage" style="color: red; display: none;"></p>
  `;

  const loginForm = document.getElementById('loginForm');
  const errorMessage = document.getElementById('errorMessage');

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = document.getElementById('email').value;
    const password = document.getElementById('password').value;

    try {
      await loginUser(email, password);
      window.location.reload();
    } catch (error) {
      errorMessage.textContent = error.message;
      errorMessage.style.display = 'block';
    }
  });
};