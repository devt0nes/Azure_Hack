# System Architecture Documentation for "Cookies Website"

## Project Overview
The "Cookies Website" is a platform built for cookie enthusiasts to explore recipes, share fun facts, and engage with the community. It is designed to provide a seamless, user-friendly experience with features such as recipe search, filtering, and user interaction through ratings and comments.

---

## Architectural Pattern
The system is implemented using a **Three-Tier Architecture**:
1. **Presentation Tier**: The frontend is developed using **React** and styled with **Bootstrap**, ensuring a responsive and interactive user interface.
2. **Application Tier**: Built with **Node.js** and **Express**, this layer handles all business logic, API endpoints, and user authentication.
3. **Data Tier**: A **MongoDB** database is used to store and manage recipes, user data, and comments.

---

## Technology Stack
The technology stack for the website includes:
- **Frontend Frameworks**: React, Bootstrap
- **Backend Frameworks**: Node.js, Express
- **Database**: MongoDB
- **Cloud Services**:
  - AWS S3 for storing recipe images
  - AWS Lambda for processing serverless functions (e.g., image optimizations)
- **Development Tools**: GitHub (version control), Postman (API testing), Jest (unit testing)

---

## Functional Requirements
1. **Homepage**:
   - Showcase featured cookie recipes.
   - Display fun facts about cookies.
2. **Recipe Database**:
   - Search and filter recipes by ingredients or categories.
   - View recipe details (ingredients, steps, and images).
3. **User Authentication**:
   - Allow users to create accounts and log in securely.
   - Enable interaction with recipes (e.g., commenting, rating).
4. **Interactive Features**:
   - Users can submit comments and rate recipes.
   - Ratings and reviews are displayed on the recipe detail page.
5. **Mobile-Responsive Design**:
   - Ensure the website works seamlessly on mobile devices.

---

## Non-Functional Requirements
- **Performance**: The system should handle standard traffic loads efficiently.
- **Scalability**: Designed to support a growing number of users and recipes.
- **Availability**: Ensure 99.9% uptime with robust infrastructure.
- **Security**:
  - Encrypt user passwords with bcrypt.
  - Use HTTPS for secure communication.
  - Implement JWT for secure authentication.
- **Compliance**: Adhere to GDPR and Cookie Law requirements.

---

## API Specifications
1. **Get Recipes** (`GET /api/recipes`):
   - Parameters: `search`, `filter`
   - Response: JSON list of recipes.
2. **Get Recipe Details** (`GET /api/recipes/:id`):
   - Parameters: `id`
   - Response: JSON object with recipe details.
3. **User Login** (`POST /api/users/login`):
   - Parameters: `username`, `password`
   - Response: JWT token for authentication.
4. **Post Comments** (`POST /api/recipes/:id/comments`):
   - Parameters: `id`, `comment`
   - Response: JSON confirmation of comment addition.

---

## Database Schema
1. **Users**:
   - Fields: `user_id`, `username`, `email`, `password_hash`, `created_at`
2. **Recipes**:
   - Fields: `recipe_id`, `title`, `description`, `ingredients`, `steps`, `author_id`, `created_at`
3. **Comments**:
   - Fields: `comment_id`, `recipe_id`, `user_id`, `comment_text`, `created_at`

---

## Security Features
- Passwords are hashed using **bcrypt** for secure storage.
- All communications are encrypted using **HTTPS**.
- JSON Web Tokens (**JWT**) are used to authenticate users.

---

## Testing Strategy
- **Unit Testing**: Use Jest for backend API testing.
- **End-to-End Testing**: Use Cypress for frontend testing.
- **Load Testing**: Use Apache JMeter to simulate high traffic and ensure performance.

---

## Deployment Plan
- **Hosting**: AWS for scalability and reliability.
- **CI/CD**: Set up automated pipelines using GitHub Actions to streamline deployment.
- **Monitoring**: Use AWS CloudWatch for monitoring application health and performance.

---

## Future Enhancements
1. Add social media sharing for recipes.
2. Implement advanced filtering options, such as dietary restrictions.
3. Introduce user-uploaded recipes with an approval workflow.

---

## Conclusion
The "Cookies Website" leverages modern web technologies and best practices to create a scalable, user-friendly, and secure platform for cookie enthusiasts. With its robust architecture, the website is well-positioned to meet current requirements and expand in the future.
