// Purpose: Contact page for customer inquiries.
// Dependencies: React

import React from 'react';

const ContactPage = () => {
  return (
    <div>
      <h1>Contact Us</h1>
      <p>We'd love to hear from you! Please fill out the form below:</p>
      <form>
        <label>
          Name:
          <input type="text" name="name" />
        </label>
        <br />
        <label>
          Email:
          <input type="email" name="email" />
        </label>
        <br />
        <label>
          Message:
          <textarea name="message"></textarea>
        </label>
        <br />
        <button type="submit">Send</button>
      </form>
    </div>
  );
};

export default ContactPage;