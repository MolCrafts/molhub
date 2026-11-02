CREATE TABLE submissions (
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

CREATE INDEX submissions_coordinate_status
  ON submissions (coordinate, status);

CREATE INDEX submissions_created_at
  ON submissions (created_at DESC);

CREATE UNIQUE INDEX submissions_one_active_coordinate
  ON submissions (coordinate)
  WHERE status IN ('pending', 'reviewing', 'accepted');

-- A merge webhook may arrive before its PR URL has been saved to submissions.
CREATE TABLE merged_pull_requests (
  url TEXT PRIMARY KEY
);
