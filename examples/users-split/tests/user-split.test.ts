/**
 * examples/users-split/tests/user-split.test.ts
 *
 * Placeholder test fixture for the users-split migration example.
 *
 * Status: FIXTURE SKELETON – real integration tests require a running
 *         database and will be implemented alongside the Code Refactor stage.
 *
 * These tests document the _intended_ behaviour after migration:
 *   - user_accounts table stores auth data
 *   - user_profiles table stores display data
 *   - Existing IDs remain stable across the migration
 */

import { USER_QUERIES } from "../dao/user-dao";

describe("users-split example fixture", () => {
  describe("USER_QUERIES", () => {
    it("references the users table (pre-migration)", () => {
      // Verify the fixture queries are correctly targeting `users`
      // (these will be the targets for AST scanning)
      expect(USER_QUERIES.FIND_BY_ID).toContain("FROM users");
      expect(USER_QUERIES.FIND_BY_EMAIL).toContain("FROM users");
      expect(USER_QUERIES.INSERT).toContain("INTO users");
      expect(USER_QUERIES.UPDATE).toContain("UPDATE users");
      expect(USER_QUERIES.DELETE).toContain("FROM users");
    });
  });

  // ── Pending integration tests (require DB) ────────────────────────────────

  it.todo("user_accounts table is created with correct columns");
  it.todo("user_profiles table is created with correct columns");
  it.todo("data is backfilled from users into user_accounts and user_profiles");
  it.todo("original user IDs are preserved in user_accounts");
  it.todo("foreign key from user_profiles.user_id → user_accounts.id is enforced");
  it.todo("legacy users table is dropped after successful backfill");
});
