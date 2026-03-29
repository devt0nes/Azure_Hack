# Restroom Finder MongoDB

## Collections
- users: User account, auth, admin/manager roles
- facilities: Public restroom/facility location, amenity and status
- reviews: Facility reviews, rating, moderation
- notifications: Status changes, alerts

## Setup
1. Edit config/db_config.js for Mongo URI.
2. Run: `node config/db_setup.js` to create indexes/seeds.

## Schema
See migrations/schema.js for collection and field definitions.
See migrations/seed_data.js for executable sample data.

## Contract Alignment
- Schema matches contracts/backend_api_contract.json endpoint requirements
- Unique constraints, indexes, data types, relationships

## Seed
Sample data covers user, facility, review, notification contracts.

