-- Create users table
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    firm_id VARCHAR(255) NOT NULL,
    firm_name VARCHAR(255),
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    email_notifications_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    notification_frequency VARCHAR(20) DEFAULT 'daily' NOT NULL,
    last_email_sent_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_firm_id ON users(firm_id);

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    firm_id VARCHAR(255),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(100),
    details JSONB,
    ip_address VARCHAR(45),
    user_agent TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_firm_id ON audit_logs(firm_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_firm_timestamp ON audit_logs(firm_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user_action ON audit_logs(user_id, action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource_type ON audit_logs(resource_type);

-- Create conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    firm_id VARCHAR(255) NOT NULL,
    title VARCHAR(500),
    meta JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_firm_id ON conversations(firm_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_conv_firm_updated ON conversations(firm_id, updated_at);

-- Create messages table
CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    sources JSONB,
    tokens_used INTEGER,
    latency_ms INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_msg_conversation_timestamp ON messages(conversation_id, timestamp);

-- Create company_profiles table
CREATE TABLE IF NOT EXISTS company_profiles (
    id SERIAL PRIMARY KEY,
    firm_id VARCHAR(255) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    registration_number VARCHAR(50),
    size VARCHAR(20),
    founded_year INTEGER,
    description TEXT,
    onboarding_completed INTEGER DEFAULT 0 NOT NULL,
    onboarding_step INTEGER DEFAULT 0 NOT NULL,
    onboarding_completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_profiles_firm_id ON company_profiles(firm_id);

-- Create company_capabilities table
CREATE TABLE IF NOT EXISTS company_capabilities (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    capability_text TEXT NOT NULL,
    category VARCHAR(100),
    years_experience INTEGER,
    qdrant_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_capabilities_company_id ON company_capabilities(company_id);
CREATE INDEX IF NOT EXISTS idx_company_capabilities_qdrant_id ON company_capabilities(qdrant_id);

-- Create past_wins table
CREATE TABLE IF NOT EXISTS past_wins (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES company_profiles(id) ON DELETE CASCADE,
    contract_title VARCHAR(500) NOT NULL,
    buyer_name VARCHAR(255) NOT NULL,
    contract_value NUMERIC(15, 2),
    award_date DATE NOT NULL,
    contract_duration_months INTEGER,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_past_wins_company_id ON past_wins(company_id);

-- Create search_preferences table
CREATE TABLE IF NOT EXISTS search_preferences (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL UNIQUE REFERENCES company_profiles(id) ON DELETE CASCADE,
    min_contract_value NUMERIC(15, 2),
    max_contract_value NUMERIC(15, 2),
    preferred_regions JSON DEFAULT '[]',
    excluded_categories JSON DEFAULT '[]',
    keywords JSON DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_search_preferences_company_id ON search_preferences(company_id);

-- Create saved_contracts table
CREATE TABLE IF NOT EXISTS saved_contracts (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    firm_id VARCHAR(255) NOT NULL,
    notice_id VARCHAR(255) NOT NULL,
    contract_title VARCHAR(500) NOT NULL,
    buyer_name VARCHAR(255) NOT NULL,
    contract_value NUMERIC(15, 2),
    deadline TIMESTAMP,
    status VARCHAR(50) DEFAULT 'interested' NOT NULL,
    notes TEXT,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_saved_contracts_user_email ON saved_contracts(user_email);
CREATE INDEX IF NOT EXISTS idx_saved_contracts_firm_id ON saved_contracts(firm_id);
CREATE INDEX IF NOT EXISTS idx_saved_contracts_notice_id ON saved_contracts(notice_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_contract ON saved_contracts(user_email, notice_id);
