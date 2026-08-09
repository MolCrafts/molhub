CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY,
  coordinate TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_yaml TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'reviewing', 'accepted', 'rejected')),
  contributor_name TEXT,
  contributor_email TEXT,
  review_note TEXT,
  pull_request_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS submissions_coordinate_status
  ON submissions (coordinate, status);

CREATE INDEX IF NOT EXISTS submissions_created_at
  ON submissions (created_at DESC);
