// Purpose: Main React application entry point
// Dependencies: react, react-router-dom
import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Homepage from './pages/Homepage';
import CancerTypes from './pages/CancerTypes';
import ContactForm from './pages/ContactForm';

function App() {
    return (
        <Router>
            <Routes>
                <Route path="/" element={<Homepage />} />
                <Route path="/cancer-types" element={<CancerTypes />} />
                <Route path="/contact" element={<ContactForm />} />
            </Routes>
        </Router>
    );
}

export default App;