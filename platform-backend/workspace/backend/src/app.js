const express = require('express');
const helmet = require('helmet');
const cors = require('cors');
const healthRouter = require('./routes/health');

const app = express();

// Security middleware
app.use(helmet());
app.use(cors());
app.use(express.json());

app.use('/api/health', healthRouter);

// Error handling middleware
app.use((err, _req, res, _next) => {
    console.error(err);
    // Handle Zod validation errors
    if (err.name === 'ZodError') {
        return res.status(400).json({ 
            error: 'Validation failed',
            details: err.errors 
        });
    }
    res.status(500).json({ error: 'Internal server error' });
});

module.exports = app;
