// Cypress end-to-end tests for the frontend and backend integration

describe('E2E Tests for User Management', () => {
    const apiUrl = 'http://localhost:5000'; // Backend API URL

    it('should register a new user', () => {
        cy.visit('/register');
        cy.get('input[name="username"]').type('testuser');
        cy.get('input[name="password"]').type('securepassword123');
        cy.get('button[type="submit"]').click();
        cy.contains('User registered successfully.').should('exist');
    });

    it('should log in and access profile page', () => {
        cy.visit('/login');
        cy.get('input[name="username"]').type('testuser');
        cy.get('input[name="password"]').type('securepassword123');
        cy.get('button[type="submit"]').click();
        cy.contains('Login successful').should('exist');

        // Access profile page
        cy.visit('/profile');
        cy.contains('Welcome, testuser!').should('exist');
    });

    it('should deny access to profile without login', () => {
        cy.visit('/profile');
        cy.contains('Unauthorized').should('exist');
    });
});