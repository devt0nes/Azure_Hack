# database_architect Notebook

## TODO
Entities:
- lore_entry: {id (UUID), title, content, game, timeline, created_at, updated_at}
- character: {id (UUID), name, created_at, updated_at}
- fanart: {id (SERIAL), character_id (UUID, FK), image_url, alt_text, created_at, updated_at}

Relationships:
- A lore entry references a game (as string, not FK, per contract)
- A character has many fanart images (one-to-many, enforced with FK)

Steps:
1. Announce plan on layer blackboard
2. Write schema.sql with 3 tables: lore_entries, characters, fanart; constraints, FKs, PKs, timestamps, indexes
3. Write representative seed_data.sql
4. Write database/README.md
5. Validate contract alignment before [READY_FOR_VERIFICATION]
