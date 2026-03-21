/**
 * Purpose: Unit tests for the Homepage React component.
 * Dependencies: React Testing Library, Jest.
 * Author: QA Engineer
 */

import React from 'react';
import { render, screen } from '@testing-library/react'; // React component testing
import '@testing-library/jest-dom'; // Extends Jest with custom matchers for DOM nodes
import Homepage from '../components/Homepage'; // Import the Homepage component to test

describe('Homepage Component', () => {
  test('renders the bakery branding', () => {
    render(<Homepage />);
    const brandingElement = screen.getByText(/Welcome to The Cupcake Bakery/i);
    expect(brandingElement).toBeInTheDocument();
  });

  test('displays featured cupcakes section', () => {
    render(<Homepage />);
    const featuredSection = screen.getByRole('heading', { name: /Featured Cupcakes/i });
    expect(featuredSection).toBeInTheDocument();
  });

  test('has responsive design elements', () => {
    render(<Homepage />);
    const mainContainer = screen.getByTestId('homepage-container');
    expect(mainContainer).toHaveClass('responsive');
  });
});