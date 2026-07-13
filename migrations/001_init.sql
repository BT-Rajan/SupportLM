-- KnowledgeLM Phase 1 schema
-- Single-tenant per install: no company_id scoping needed across tables,
-- `company` is a single-row settings-like table for the install's own profile.

CREATE TABLE company (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    name            VARCHAR(255) NOT NULL,
    profile_json    JSON NULL,           -- free-form profile fields (industry, about, etc.)
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE agent (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    name            VARCHAR(100) NOT NULL DEFAULT 'Assistant',
    persona         TEXT NULL,           -- system-prompt style persona/instructions
    theme_json      JSON NULL,           -- colors, logo url, etc.
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE category (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    name            VARCHAR(150) NOT NULL,
    slug            VARCHAR(150) NOT NULL UNIQUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    category_id     INT NULL,
    title           VARCHAR(255) NOT NULL,
    filename        VARCHAR(255) NOT NULL,
    raw_markdown    LONGTEXT NOT NULL,
    status          ENUM('pending','processing','ready','error') NOT NULL DEFAULT 'pending',
    error_message   TEXT NULL,
    uploaded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at    TIMESTAMP NULL,
    FOREIGN KEY (category_id) REFERENCES category(id) ON DELETE SET NULL
);

CREATE TABLE document_chunk (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    document_id     INT NOT NULL,
    chunk_index     INT NOT NULL,        -- order within document
    heading_path    VARCHAR(500) NULL,   -- e.g. "Setup > Installation" for citation context
    content         TEXT NOT NULL,
    token_count     INT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES document(id) ON DELETE CASCADE,
    INDEX idx_document_chunk_doc (document_id)
);

CREATE TABLE embedding (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    chunk_id        INT NOT NULL UNIQUE,
    model           VARCHAR(100) NOT NULL,
    dims            INT NOT NULL,
    vector          JSON NOT NULL,       -- float array; brute-force cosine sim in app layer
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chunk_id) REFERENCES document_chunk(id) ON DELETE CASCADE
);

CREATE TABLE conversation (
    id              CHAR(36) PRIMARY KEY,   -- UUID
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    visitor_label   VARCHAR(150) NULL       -- optional, no PII required
);

CREATE TABLE message (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    conversation_id CHAR(36) NOT NULL,
    role            ENUM('user','assistant') NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversation(id) ON DELETE CASCADE,
    INDEX idx_message_conv (conversation_id)
);

CREATE TABLE citation (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    message_id      INT NOT NULL,
    chunk_id        INT NOT NULL,
    rank            INT NOT NULL,           -- 1 = most relevant
    similarity      FLOAT NULL,
    FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES document_chunk(id) ON DELETE CASCADE
);

CREATE TABLE admin_user (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    role            ENUM('owner','admin') NOT NULL DEFAULT 'admin',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at   TIMESTAMP NULL
);

CREATE TABLE app_setting (
    setting_key     VARCHAR(150) PRIMARY KEY,
    setting_value   TEXT NULL,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE usage_log (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    event_type      VARCHAR(50) NOT NULL,   -- 'chat_message', 'document_upload', ...
    event_meta      JSON NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_usage_log_type_time (event_type, created_at)
);
