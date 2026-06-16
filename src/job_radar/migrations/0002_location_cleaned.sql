-- Normalised UK city, computed at ingest from `location` (see locations.py).
-- Lets the dashboard / Telegram / SQL group by a clean city instead of raw text.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS location_cleaned VARCHAR;
