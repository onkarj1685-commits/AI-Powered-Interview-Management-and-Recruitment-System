-- =============================================================================
-- Migration: Add Google Authentication (OAuth 2.0) fields to PostgreSQL users table
-- AI-Powered Interview Management and Recruitment System
-- =============================================================================

-- 1. Create users table if it does not already exist
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    google_id VARCHAR(120) UNIQUE,
    name VARCHAR(120),
    full_name VARCHAR(120),
    email VARCHAR(120) UNIQUE NOT NULL,
    username VARCHAR(80) UNIQUE,
    hashed_password VARCHAR(255),
    profile_picture VARCHAR(500),
    role VARCHAR(50) NOT NULL DEFAULT 'HR/User',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc'),
    last_login TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc')
);

-- 2. If table already exists, safely add any missing columns (Idempotent)
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS name VARCHAR(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_picture VARCHAR(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'HR/User';
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc');
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITHOUT TIME ZONE DEFAULT (NOW() AT TIME ZONE 'utc');

-- 3. Ensure columns are nullable for Google OAuth users (who have no local password)
ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;
ALTER TABLE users ALTER COLUMN username DROP NOT NULL;

-- 4. Create performance and unique indexes
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_username ON users (username);

-- 5. Seed default admin account if table is completely empty
INSERT INTO users (email, username, name, full_name, hashed_password, role, created_at, last_login)
SELECT 
    'admin@interview.com',
    'admin',
    'System Administrator',
    'System Administrator',
    -- Default bcrypt hash for 'Admin123!'
    '$2b$12$e6m7x.p6PsqyYk5nI0nKx.kM6uIqj73hG3gJ4oEa8ZfS.C7i5l0aW',
    'admin',
    NOW() AT TIME ZONE 'utc',
    NOW() AT TIME ZONE 'utc'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin' OR email = 'admin@interview.com');
