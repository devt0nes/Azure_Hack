/**
 * Purpose: Security configuration for the cupcake bakery demo website.
 * Author: Security Engineer
 * Dependencies: helmet, express-rate-limit, xss-clean, bcryptjs, jsonwebtoken
 * Description: This file implements security mechanisms including HTTPS enforcement, 
 * input sanitization, API security, and sensitive data encryption.
 */

// Importing required packages
const helmet = require('helmet'); // For setting secure HTTP headers
const rateLimit = require('express-rate-limit'); // For rate limiting requests
const xssClean = require('xss-clean'); // For sanitizing user inputs to prevent XSS attacks
const bcrypt = require('bcryptjs'); // For encrypting sensitive data
const jwt = require('jsonwebtoken'); // For securing API access via JWT

// Express middleware for security setup
module.exports = function (app) {
    /**
     * Enforce HTTPS using Helmet
     */
    app.use(helmet());

    /**
     * Rate limiting
     * This limits repeated requests to public APIs and protects against brute-force attacks.
     */
    const limiter = rateLimit({
        windowMs: 15 * 60 * 1000, // 15-minute window
        max: 100, // Limit each IP to 100 requests per windowMs
        message: "Too many requests from this IP, please try again later.",
    });
    app.use('/api/', limiter);

    /**
     * Prevent cross-site scripting (XSS) attacks
     */
    app.use(xssClean());

    /**
     * JWT Token Verification Middleware
     * Verifies the authenticity of tokens for secure API access.
     */
    app.use((req, res, next) => {
        if (req.headers['authorization']) {
            const token = req.headers['authorization'].split(' ')[1];
            try {
                const decoded = jwt.verify(token, process.env.JWT_SECRET);
                req.user = decoded; // Attach decoded user info to request object
                next();
            } catch (error) {
                return res.status(401).json({ message: 'Invalid or expired token.' });
            }
        } else {
            next(); // If no token, proceed without user info
        }
    });

    /**
     * Encrypt sensitive data using bcrypt
     * Utility function to hash sensitive information (e.g., passwords).
     * @param {string} data - The sensitive data to hash
     * @returns {Promise<string>} - The hashed data
     */
    app.locals.hashData = async function (data) {
        const salt = await bcrypt.genSalt(10);
        return bcrypt.hash(data, salt);
    };

    console.log('Security configurations have been successfully applied.');
};