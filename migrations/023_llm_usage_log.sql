-- Phase 7 — 0.3: Token & cost capture schema
--
-- One row per assistant message — `message_id` UNIQUE, same
-- one-per-message shape as `message_feedback`/`service_request`. This
-- is the foundation both 1.0 (usage dashboard) and 4.0 (cost
-- tracking) aggregate from.
--
-- `estimated_cost_usd` is DECIMAL(10,6), not FLOAT — cost figures are
-- summed across many rows for dashboard totals, and floating-point
-- summation error compounds; DECIMAL avoids that at the cost of a
-- slightly larger column, which is irrelevant at this table's size.
--
-- Safe to re-run: CREATE TABLE IF NOT EXISTS is idempotent.

CREATE TABLE IF NOT EXISTS llm_usage_log (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id           INT NOT NULL,
    message_id          INT NOT NULL,
    provider            VARCHAR(20) NOT NULL,
    model               VARCHAR(100) NOT NULL,
    input_tokens        INT NOT NULL,
    output_tokens       INT NOT NULL,
    estimated_cost_usd  DECIMAL(10, 6) NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenant(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE,
    UNIQUE KEY uq_llm_usage_log_message (message_id),
    KEY idx_llm_usage_log_tenant_created (tenant_id, created_at)
);
