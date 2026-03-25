-- Sample data for lore_entries table
INSERT INTO lore_entries (id, title, content, game, timeline, created_at, updated_at) VALUES
  ('aeac7651-bf22-4a44-bc18-cdd2d787a001', 'The Bite of 87', 'The infamous incident that changed FNaF forever.', 'FNaF1', '1987', NOW(), NOW()),
  ('bfed681c-6eea-4b2b-b9ca-9969ac656aa2', 'The Missing Children', 'Children disappear at Freddy Fazbear''s Pizza.', 'FNaF1', '1985', NOW(), NOW()),
  ('c1d2e155-10a3-472f-bc96-8824938efe3b', 'Springlock Failure', 'First documented springlock suit failure.', 'FNaF3', '1983', NOW(), NOW()),
  ('d2f17e6b-feef-4e94-b644-7efe0083935b', 'The Puppet''s Origin', 'A soul inhabits the Puppet.', 'FNaF2', '1987', NOW(), NOW()),
  ('e2704d8d-c6b5-41b5-98a3-d1a9c92b059c', 'Purple Guy Captured', 'The identity of the murderer revealed.', 'FNaF3', '1993', NOW(), NOW());

-- Sample data for characters table
INSERT INTO characters (id, name, created_at, updated_at) VALUES
  ('c749f937-0be6-47d2-95f2-6761a25efee4', 'Freddy Fazbear', NOW(), NOW()),
  ('e8e6eb92-249d-4726-8202-20158176cdeb', 'Bonnie', NOW(), NOW()),
  ('fbd9d081-cd82-41e2-855c-384d3e23ae1a', 'Chica', NOW(), NOW()),
  ('ff2e7d05-7f13-4b33-8e7a-c551f3271d99', 'Foxy', NOW(), NOW()),
  ('4a3eb223-8d9b-4fec-9ff1-7fed8193fca8', 'The Puppet', NOW(), NOW());

-- Sample data for fanart table (multiple images per character)
INSERT INTO fanart (character_id, image_url, alt_text, created_at, updated_at) VALUES
  ('c749f937-0be6-47d2-95f2-6761a25efee4', 'https://images.fnaf.com/freddy1.png', 'Freddy pose 1', NOW(), NOW()),
  ('c749f937-0be6-47d2-95f2-6761a25efee4', 'https://images.fnaf.com/freddy2.png', 'Freddy in the office', NOW(), NOW()),
  ('e8e6eb92-249d-4726-8202-20158176cdeb', 'https://images.fnaf.com/bonnie1.png', 'Bonnie on stage', NOW(), NOW()),
  ('e8e6eb92-249d-4726-8202-20158176cdeb', 'https://images.fnaf.com/bonnie2.png', 'Bonnie jumpscare', NOW(), NOW()),
  ('fbd9d081-cd82-41e2-855c-384d3e23ae1a', 'https://images.fnaf.com/chica1.png', 'Chica with cupcake', NOW(), NOW()),
  ('ff2e7d05-7f13-4b33-8e7a-c551f3271d99', 'https://images.fnaf.com/foxy1.png', 'Foxy running', NOW(), NOW()),
  ('4a3eb223-8d9b-4fec-9ff1-7fed8193fca8', 'https://images.fnaf.com/puppet1.png', 'The Puppet''s mask', NOW(), NOW()),
  ('fbd9d081-cd82-41e2-855c-384d3e23ae1a', 'https://images.fnaf.com/chica2.png', 'Chica in the dark', NOW(), NOW()),
  ('ff2e7d05-7f13-4b33-8e7a-c551f3271d99', 'https://images.fnaf.com/foxy2.png', 'Foxy in Pirate Cove', NOW(), NOW()),
  ('4a3eb223-8d9b-4fec-9ff1-7fed8193fca8', 'https://images.fnaf.com/puppet2.png', 'The Puppet floating', NOW(), NOW());
