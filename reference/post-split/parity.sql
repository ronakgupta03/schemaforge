-- Data-preservation assertions for the users -> users + user_profiles split.
-- Run AFTER the migration; every boolean column must be true.
SELECT
    (SELECT count(*) FROM users) = (SELECT count(*) FROM user_profiles)
        AS profiles_complete,
    (SELECT count(*) FROM user_profiles WHERE address IS NULL) = 0
        AS no_null_addresses,
    (SELECT count(*) FROM users u LEFT JOIN user_profiles p ON p.user_id = u.id
       WHERE p.id IS NULL) = 0
        AS all_users_have_profiles;