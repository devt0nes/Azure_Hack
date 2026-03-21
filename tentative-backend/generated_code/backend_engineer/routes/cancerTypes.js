/**
 * Purpose: Define routes for fetching cancer type information.
 * Dependencies: express
 * Author: Backend Engineer
 */

const express = require('express');
const router = express.Router();

// Mock data for cancer types
const cancerTypes = [
  {
    id: '1',
    name: 'Breast Cancer',
    description: 'A type of cancer that forms in the cells of the breasts.',
  },
  {
    id: '2',
    name: 'Lung Cancer',
    description: 'A type of cancer that begins in the lungs.',
  },
  {
    id: '3',
    name: 'Prostate Cancer',
    description: 'Cancer in a man’s prostate, a small walnut-shaped gland.',
  },
];

// Route to fetch all cancer types
router.get('/', (req, res) => {
  res.status(200).json(cancerTypes);
});

module.exports = router;