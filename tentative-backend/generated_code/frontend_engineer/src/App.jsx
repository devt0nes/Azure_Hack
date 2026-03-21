// Purpose: Main application component that handles routing.
// Dependencies: react-router-dom for routing

import React from 'react';
import { Routes, Route } from 'react-router-dom';
import HomePage from './pages/HomePage.jsx';
import OrderPage from './pages/OrderPage.jsx';
import ContactPage from './pages/ContactPage.jsx';

const App = () => {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/order" element={<OrderPage />} />
      <Route path="/contact" element={<ContactPage />} />
    </Routes>
  );
};

export default App;