-- Migration: Add prompt_template column to characters table
-- Date: 2025-12-14
-- Description: Adds support for multiple prompt formats (pygmalion, alpaca, chatml)

-- Add the prompt_template column with default value 'pygmalion'
ALTER TABLE characters
ADD COLUMN IF NOT EXISTS prompt_template VARCHAR(50) NOT NULL DEFAULT 'pygmalion';

-- Update any existing characters to use pygmalion template (the original format)
UPDATE characters
SET prompt_template = 'pygmalion'
WHERE prompt_template IS NULL OR prompt_template = '';

-- Verify migration
SELECT
    COUNT(*) as total_characters,
    prompt_template,
    COUNT(*) as count_per_template
FROM characters
GROUP BY prompt_template;
