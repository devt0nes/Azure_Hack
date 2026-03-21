// Purpose: Displays product catalog with images, descriptions, and pricing.
// Dependencies: React
// Author: Frontend Engineer

import React, { useEffect, useState } from 'react';

const ProductCatalog = () => {
    const [products, setProducts] = useState([]);
    
    useEffect(() => {
        fetch('/api/products')
            .then((response) => response.json())
            .then((data) => setProducts(data));
    }, []);
    
    return (
        <div className="product-catalog">
            <h1>Our Products</h1>
            <div className="products">
                {products.map((product) => (
                    <div className="product" key={product.id}>
                        <img src={product.image_url} alt={product.name} />
                        <h2>{product.name}</h2>
                        <p>{product.description}</p>
                        <p>${product.price.toFixed(2)}</p>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default ProductCatalog;