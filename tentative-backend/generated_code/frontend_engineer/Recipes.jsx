import React, { useState } from 'react';

const Recipes = () => {
  const [searchTerm, setSearchTerm] = useState('');

  const handleSearch = (e) => {
    setSearchTerm(e.target.value);
  };

  return (
    <div className="recipes">
      <h2>Recipe Database</h2>
      <input
        type="text"
        placeholder="Search recipes..."
        value={searchTerm}
        onChange={handleSearch}
      />
      {/* Recipe list will be rendered here */}
    </div>
  );
};

export default Recipes;