import React from 'react';
import { useParams } from 'react-router-dom';

const RecipeDetail = () => {
  const { id } = useParams();

  return (
    <div className="recipe-detail">
      <h2>Recipe Details</h2>
      <p>Details for recipe ID: {id}</p>
      {/* Ingredients, steps, and reviews will be shown here */}
    </div>
  );
};

export default RecipeDetail;