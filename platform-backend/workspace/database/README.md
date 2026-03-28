# ShoeMart MongoDB Database Layer

## Collections
- complaints: stores complaint metadata and statuses
- complaint_chats: stores chat interactions for complaint threads

## Indexes
- complaints.complaint_id (unique)
- complaints.user_id (lookup)
- complaint_chats.complaint_id (lookup)

## Setup
Run `node config/db_setup.js` to create schema and insert seed records.

## Contract Alignment
Schema covers all fields/flows for complaint submission, status, chat, and escalation as defined in contracts/backend_api_contract.json.