-- Phase 1 — 5.1: Plan tier structure
--
-- Formalizes the tier table `tenant.plan_tier` has pointed to since
-- 002_tenant_org.sql ("5.1 will formalize the tier table this points
-- at"). Three tiers, confirmed with the owner:
--
--   starter:      25 docs,   500 messages/month,  2 seats
--   pro:         200 docs, 5,000 messages/month, 10 seats
--   enterprise: unlimited on all three (NULL = unlimited)
--
-- Existing tenants were seeded with plan_tier = 'free' by 002/004,
-- before this table existed — 'free' was always a placeholder, never
-- a real tier name. This migration remaps them to 'starter' before
-- adding the FK, so no existing row is left dangling.
--
-- Safe to re-run on a fresh install (drops first, like earlier
-- structural migrations).

DROP TABLE IF EXISTS plan_tier;

CREATE TABLE plan_tier (
    slug              VARCHAR(50) PRIMARY KEY,
    display_name      VARCHAR(100) NOT NULL,
    doc_limit         INT NULL,   -- NULL = unlimited
    message_limit     INT NULL,   -- NULL = unlimited; counted per calendar month
    seat_limit        INT NULL,   -- NULL = unlimited; not enforced until Phase 2
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO plan_tier (slug, display_name, doc_limit, message_limit, seat_limit) VALUES
    ('starter',    'Starter',    25,   500,  2),
    ('pro',        'Pro',        200,  5000, 10),
    ('enterprise', 'Enterprise', NULL, NULL, NULL);

-- Remap the placeholder value before the FK below would reject it.
UPDATE tenant SET plan_tier = 'starter' WHERE plan_tier = 'free';

ALTER TABLE tenant DROP FOREIGN KEY IF EXISTS fk_tenant_plan_tier;
ALTER TABLE tenant
    MODIFY COLUMN plan_tier VARCHAR(50) NOT NULL DEFAULT 'starter',
    ADD CONSTRAINT fk_tenant_plan_tier FOREIGN KEY (plan_tier) REFERENCES plan_tier(slug);
