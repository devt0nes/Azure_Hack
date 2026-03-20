import React from 'react';
import { Link } from 'react-router-dom';

const Navbar = () => {
    return (
        <nav className="bg-blue-600 text-white p-4">
            <div className="container mx-auto flex justify-between">
                <Link to="/" className="text-xl font-bold">Cookie Hub</Link>
                <div className="space-x-4">
                    <Link to="/recipes" className="hover:underline">Recipes</Link>
                    <Link to="/blog" className="hover:underline">Blog</Link>
                    <Link to="/contact" className="hover:underline">Contact</Link>
                </div>
            </div>
        </nav>
    );
};

export default Navbar;