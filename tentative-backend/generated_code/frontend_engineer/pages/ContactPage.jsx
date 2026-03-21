// Purpose: Contact form page for inquiries about cancer awareness.
// Dependencies: React

import React from 'react';

function ContactPage() {
    return (
        <div>
            <h1>Contact Us</h1>
            <p>Fill out the form below to reach out to us with your questions or concerns.</p>
            <form>
                <label>
                    Name:
                    <input type="text" name="name" required />
                </label>
                <br />
                <label>
                    Email:
                    <input type="email" name="email" required />
                </label>
                <br />
                <label>
                    Message:
                    <textarea name="message" required></textarea>
                </label>
                <br />
                <button type="submit">Submit</button>
            </form>
        </div>
    );
}

export default ContactPage;