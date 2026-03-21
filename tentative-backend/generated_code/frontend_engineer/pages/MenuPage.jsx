// Purpose: Menu page component for displaying cupcake offerings
// Dependencies: React

import React from 'react';

const MenuPage = () => {
    return (
        <div className="container">
            <h1>Our Menu</h1>
            <p>Check out our delicious cupcake offerings below:</p>
            <ul>
                <li>Chocolate Bliss - $3.99</li>
                <li>Vanilla Dream - $3.49</li>
                <li>Red Velvet Delight - $4.49</li>
            </ul>
        </div>
    );
};

export default MenuPage;