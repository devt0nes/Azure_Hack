import React from 'react';

const ContactPage = () => {
    return (
        <div className="p-4">
            <h1 className="text-4xl font-bold">Contact Us</h1>
            <p className="mt-2 text-lg">
                Have questions or feedback? Fill out the form below and reach out to us!
            </p>
            <form className="mt-4">
                <label className="block mb-2 text-sm font-bold" htmlFor="name">Name</label>
                <input className="w-full px-3 py-2 border rounded" id="name" type="text" placeholder="Your Name" />

                <label className="block mt-4 mb-2 text-sm font-bold" htmlFor="email">Email</label>
                <input className="w-full px-3 py-2 border rounded" id="email" type="email" placeholder="Your Email" />

                <label className="block mt-4 mb-2 text-sm font-bold" htmlFor="message">Message</label>
                <textarea className="w-full px-3 py-2 border rounded" id="message" rows="4" placeholder="Your Message"></textarea>

                <button className="mt-4 px-4 py-2 bg-blue-500 text-white rounded" type="submit">Send</button>
            </form>
        </div>
    );
};

export default ContactPage;