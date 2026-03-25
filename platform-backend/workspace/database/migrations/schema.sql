-- SQL schema for Game Marketplace: Lore, Characters, Fanart
-- Table: lore_entries (from /api/lore)
CREATE TABLE IF NOT EXISTS lore_entries (
    id UUID PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    game VARCHAR(100),
    timeline VARCHAR(100),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Table: characters (from /api/characters)
CREATE TABLE IF NOT EXISTS characters (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Table: fanart (stores multiple images per character)
CREATE TABLE IF NOT EXISTS fanart (
    id SERIAL PRIMARY KEY,
    character_id UUID NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    alt_text VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_lore_entries_game ON lore_entries(game);
CREATE INDEX IF NOT EXISTS idx_lore_entries_timeline ON lore_entries(timeline);
CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
CREATE INDEX IF NOT EXISTS idx_fanart_character_id ON fanart(character_id);
