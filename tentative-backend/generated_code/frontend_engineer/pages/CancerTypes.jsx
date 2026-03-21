// Purpose: Informational page about different types of cancer
// Dependencies: react
import React from 'react';

function CancerTypes() {
    return (
        <div className="cancer-types">
            <h1>Types of Cancer</h1>
            <ul>
                <li>Breast Cancer</li>
                <li>Lung Cancer</li>
                <li>Prostate Cancer</li>
                <li>Skin Cancer</li>
            </ul>
        </div>
    );
}

export default CancerTypes;