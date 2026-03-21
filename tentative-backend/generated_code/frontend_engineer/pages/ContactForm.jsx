// Purpose: Contact form for inquiries
// Dependencies: react
import React, { useState } from 'react';

function ContactForm() {
    const [formData, setFormData] = useState({ name: '', email: '', message: '' });

    const handleSubmit = (e) => {
        e.preventDefault();
        console.log('Form submitted:', formData);
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData({ ...formData, [name]: value });
    };

    return (
        <form onSubmit={handleSubmit}>
            <h1>Contact Us</h1>
            <label>Name:</label>
            <input type="text" name="name" value={formData.name} onChange={handleChange} required />
            <label>Email:</label>
            <input type="email" name="email" value={formData.email} onChange={handleChange} required />
            <label>Message:</label>
            <textarea name="message" value={formData.message} onChange={handleChange} required />
            <button type="submit">Submit</button>
        </form>
    );
}

export default ContactForm;