-- Phase 3: extend feedback + training_labels for approve/edit/reject workflow

-- feedback: add action + edited_reply columns (keep thumb/notes for compat)
ALTER TABLE feedback ADD COLUMN action TEXT;
ALTER TABLE feedback ADD COLUMN edited_reply TEXT;

-- training_labels: add float label + timestamp (label col stays INTEGER for compat)
ALTER TABLE training_labels ADD COLUMN label_float REAL;
ALTER TABLE training_labels ADD COLUMN ts TEXT;
