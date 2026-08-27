-- name: find_by_email
SELECT id, name, email FROM users WHERE email = 'user1@example.com';

-- name: recent_users
SELECT id, name FROM users ORDER BY id DESC LIMIT 20;

-- name: addresses_report
SELECT u.name, p.address FROM users u JOIN user_profiles p ON p.user_id = u.id ORDER BY u.id LIMIT 20;
