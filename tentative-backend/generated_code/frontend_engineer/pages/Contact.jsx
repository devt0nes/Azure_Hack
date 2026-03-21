// Purpose: Contact component displaying a contact form for user inquiries
// Dependencies: React

import React from 'react';

const Contact = () => {
    return (
        <div>
            <h1>Contact Us</h1>
            <form>
                <label>
                    Name:
                    <input type="text" name="name" required />
                </label>
                <label>
                    Email:
                    <input type="email" name="email" required />
                </label>
                <label>
                    Message:
                    <textarea name="message" required></textarea>
                </label>
                <button type="submit">Submit</button>
            </form>
        </div>
    );
};

export default Contact;