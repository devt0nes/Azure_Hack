# Game Marketplace Platform Database Schema

This database handles FNaF lore and character data for lore browsing and fanart viewing on the platform as per system contract.

## Tables

### lore_entries
- **id:** UUID, primary key
- **title:** Title of the lore entry
- **content:** Body of the lore entry
- **game:** Game name/series (searchable)
- **timeline:** Timeline string (optional, searchable)
- **created_at:** Timestamp
- **updated_at:** Timestamp

### characters
- **id:** UUID, primary key
- **name:** Character name, unique
- **created_at:** Timestamp
- **updated_at:** Timestamp

### fanart
- **id:** SERIAL PK
- **character_id:** UUID, references characters(id), not null, on delete cascade
- **image_url:** Fanart image URL
- **alt_text:** Alt text for accessibility
- **created_at:** Timestamp
- **updated_at:** Timestamp

## Relationships
- One character can have many fanart entries (see fanart.character_id foreign key)
- Lore entries are independent by contract, game/timeline are text fields

## Indices
- Indices on lore_entries.game, lore_entries.timeline, and characters.name for efficient searching
- Fanart indexed on character_id

## Migrations
- See migrations/schema.sql

## Sample Data
- See migrations/seed_data.sql

## Security
- No PII stored; all public display data.
- Ensure only valid URLs are allowed for fanart through backend validation (not enforced at DB layer).
