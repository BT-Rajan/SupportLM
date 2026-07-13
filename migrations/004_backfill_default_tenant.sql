-- Phase 1 — 1.3: Backfill migration for existing data
--
-- Unlike 001/002/003, this is a ONE-TIME migration, not safe to re-run
-- once it has completed (it drops `company` and tightens columns to
-- NOT NULL). Run it exactly once, against a backup, per 6.1.
--
-- What it does, in order:
--   1. Creates a single default tenant, absorbing `company`'s
--      name/profile_json if a `company` row exists (per the 1.1
--      proposal's fold-in decision).
--   2. Stamps every existing row in the 1.2-retrofitted tables with
--      that tenant's id.
--   3. Links every existing `admin_user` to the default tenant via
--      `tenant_user` with role 'owner' — without this, no admin could
--      pass a tenant-scoped access check once 3.0 lands. This wasn't
--      spelled out in the WBS item but follows directly from 1.1's
--      "ownership assignable from Phase 1" goal.
--   4. Drops `company` (now redundant).
--   5. Converts `tenant_id` on all 8 tables to NOT NULL, now that every
--      row has a value.

-- 1. Default tenant, folding in `company` if present.
INSERT INTO tenant (name, slug, plan_tier, status, profile_json)
SELECT
    COALESCE((SELECT name FROM company ORDER BY id LIMIT 1), 'Default Tenant'),
    'default',
    'free',
    'active',
    (SELECT profile_json FROM company ORDER BY id LIMIT 1)
WHERE NOT EXISTS (SELECT 1 FROM tenant WHERE slug = 'default');

SET @default_tenant_id = (SELECT id FROM tenant WHERE slug = 'default' LIMIT 1);

-- 2. Stamp existing rows.
UPDATE document        SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE document_chunk  SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE embedding        SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE category         SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE conversation     SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE message          SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE citation         SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;
UPDATE agent            SET tenant_id = @default_tenant_id WHERE tenant_id IS NULL;

-- 3. Link existing admins to the default tenant as owner.
INSERT INTO tenant_user (tenant_id, admin_id, role)
SELECT @default_tenant_id, au.id, 'owner'
FROM admin_user au
WHERE NOT EXISTS (
    SELECT 1 FROM tenant_user tu
    WHERE tu.tenant_id = @default_tenant_id AND tu.admin_id = au.id
);

-- 4. Drop the now-redundant company table.
DROP TABLE IF EXISTS company;

-- 5. Tighten to NOT NULL now that every row is stamped.
ALTER TABLE document        MODIFY tenant_id INT NOT NULL;
ALTER TABLE document_chunk  MODIFY tenant_id INT NOT NULL;
ALTER TABLE embedding        MODIFY tenant_id INT NOT NULL;
ALTER TABLE category         MODIFY tenant_id INT NOT NULL;
ALTER TABLE conversation     MODIFY tenant_id INT NOT NULL;
ALTER TABLE message          MODIFY tenant_id INT NOT NULL;
ALTER TABLE citation         MODIFY tenant_id INT NOT NULL;
ALTER TABLE agent            MODIFY tenant_id INT NOT NULL;
