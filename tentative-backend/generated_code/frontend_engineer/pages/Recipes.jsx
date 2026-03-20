import React, { useState, useEffect } from 'react';

const Recipes = () => {
  const [recipes, setRecipes] = useState([]);

  useEffect(() => {
    fetch('/api/recipes')
      .then(response => response.json())
      .then(data => setRecipes(data));
  }, []);

  return (
    <div>
      <h1>Recipes</h1>
      <ul>
        {recipes.map(recipe => (
          <li key={recipe.recipe_id}>{recipe.title}</li>
        ))}
      </ul>
    </div>
  );
};

export default Recipes;