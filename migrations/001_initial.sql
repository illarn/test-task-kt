BEGIN;

-- published_offers and draft_offers store JSON arrays of offer objects.
-- [{"offer_id": 18001, "share": 100, "state": "active", "pinned": false, "removed": false}]
CREATE TABLE IF NOT EXISTS stream_state (
    stream_id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    published_offers TEXT NOT NULL CHECK (json_type(published_offers) = 'array'),
    draft_offers TEXT CHECK (draft_offers IS NULL OR json_type(draft_offers) = 'array')
);

COMMIT;
