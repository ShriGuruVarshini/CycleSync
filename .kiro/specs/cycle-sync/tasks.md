# Implementation Plan: CycleSync

## Overview

Implement CycleSync on AWS serverless infrastructure. Lambda functions are written in Python 3.12, the frontend is a plain HTML/CSS/JS SPA served locally or from any static host, and infrastructure is defined with AWS SAM or CDK. Tasks are ordered to build foundational layers first (IaC, DynamoDB tables, auth, core Lambdas) and wire everything together at the end. Auth uses DynamoDB-backed hashed passwords and opaque session tokens (no Cognito). Notifications are written to DynamoDB (no SNS/SES). Data is stored as plaintext in DynamoDB (no KMS).

## Tasks

- [x] 1. Project setup and infrastructure scaffolding
  - Initialize Python Lambda project structure: `lambdas/` directory with one subdirectory per function (`cycle_tracker`, `mood_tracker`, `prediction_engine`, `recommendation_engine`, `notification_service`, `dashboard`)
  - Add `requirements.txt` per Lambda with `boto3` and `hypothesis` for test functions; add shared `layers/common/` for shared utilities
  - Create AWS SAM `template.yaml` (or CDK stack) defining all DynamoDB tables with keys, GSIs, and TTL:
    - `cyclesync-users` (PK: `user_id`, GSI: `email-index` on `email`)
    - `cyclesync-sessions` (PK: `token`, TTL attribute: `ttl`)
    - `cyclesync-mood-entries` (PK: `user_id`, SK: `entry_date`)
    - `cyclesync-content-items` (PK: `item_id`, GSIs: `category-index`, `mood-tags-index`, `language-index`)
    - `cyclesync-notification-logs` (PK: `user_id`, SK: `sent_at`)
    - `cyclesync-notifications` (PK: `user_id`, SK: `created_at`)
  - Configure HTTPS enforcement: API Gateway with TLS-only
  - _Requirements: 12.1, 12.2_

- [x] 2. Auth Lambda (DynamoDB-backed)
  - [x] 2.1 Implement registration, login, and logout handlers in the auth Lambda
    - Registration: hash password with `bcrypt`, store user record in `cyclesync-users` (PK: `user_id` UUID, GSI: `email-index`); return 409 on duplicate email
    - Login: look up user by email via `email-index` GSI, verify bcrypt hash; on success generate a random opaque token, write to `cyclesync-sessions` (PK: `token`, `user_id`, `expires_at`, `ttl`); return token
    - Logout: delete the session record from `cyclesync-sessions` by token; return 200
    - Token auth middleware (shared utility): read `Authorization: Bearer <token>` header, look up token in `cyclesync-sessions`, check `expires_at`; return 401 if missing/expired; inject `user_id` into handler context
    - _Requirements: 1.1, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4_

  - [x] 2.2 Write property test for registration validation (Property 1)
    - **Property 1: Registration rejects missing required fields**
    - **Validates: Requirements 1.1**

  - [x] 2.3 Write property test for registration round-trip (Property 2)
    - **Property 2: Registration round-trip**
    - **Validates: Requirements 1.2**

  - [x] 2.4 Write property test for password minimum length (Property 3)
    - **Property 3: Password minimum length enforcement**
    - **Validates: Requirements 1.4**

  - [x] 2.5 Write property test for password hashing (Property 4)
    - **Property 4: Passwords are never stored in plaintext**
    - **Validates: Requirements 1.5**

  - [x] 2.6 Implement `POST /auth/forgot-password` and `POST /auth/confirm-forgot-password` Lambda handlers
    - `POST /auth/forgot-password`: generate a short-lived verification code, store it in `cyclesync-sessions` (or a dedicated field on the user record) with a 15-minute TTL; always return generic 200 ("If this email is registered, you will receive a reset code") regardless of whether the email exists
    - `POST /auth/confirm-forgot-password`: look up the code by email, verify it is not expired; on match call `UpdateItem` on `cyclesync-users` to store the new bcrypt-hashed password; return 200 on success; return 400 on invalid/expired code
    - Both endpoints are unauthenticated (no token middleware)
    - _Requirements: 2b.1, 2b.2, 2b.3, 2b.4, 2b.5, 2b.6_

  - [x] 2.7 Write property test for login round-trip (Property 5)
    - **Property 5: Login round-trip**
    - **Validates: Requirements 2.1**

  - [x] 2.8 Write property test for logout invalidates session (Property 7)
    - **Property 7: Logout invalidates session**
    - **Validates: Requirements 2.4**

  - [x] 2.9 Write property test for session expiry (Property 6)
    - **Property 6: Session expiry after inactivity**
    - **Validates: Requirements 2.3**

- [x] 3. Checkpoint — Ensure all auth tests pass, ask the user if questions arise.

- [x] 4. Profile and hobby preference management
  - [x] 4.1 Implement `GET /profile` and `PUT /profile` Lambda handlers
    - GET: read from `cyclesync-users` by `user_id` (from session token middleware)
    - PUT: validate fields (cycle_length 21–45), call `UpdateItem` on `cyclesync-users`; return 400 with `{ error, message }` on validation failures
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 4.2 Write property test for profile update round-trip (Property 8)
    - **Property 8: Profile update round-trip**
    - **Validates: Requirements 3.1**

  - [x] 4.3 Write property test for cycle length validation (Property 9)
    - **Property 9: Cycle length validation**
    - **Validates: Requirements 3.3**

  - [x] 4.4 Implement `PUT /profile/hobbies` Lambda handler
    - Accept list subset of ["Songs", "Movies", "Poetry", "Digital Colouring"], call `UpdateItem` on `cyclesync-users`
    - Default to all four categories when list is empty
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 4.5 Write property test for hobby preference persistence (Property 18)
    - **Property 18: Hobby preference persistence round-trip**
    - **Validates: Requirements 7.3, 7.4**

  - [x] 4.6 Implement language preference update in `PUT /profile` handler
    - Accept `language_preference` field (BCP 47 code string), call `UpdateItem` on `cyclesync-users`
    - _Requirements: 7.6, 7.7_

- [x] 5. cycle_tracker Lambda
  - [x] 5.1 Implement `calculate_phase(last_period_date, cycle_length, today)` pure Python function
    - `day_in_cycle = ((today - last_period_date).days % cycle_length) + 1`
    - Map to Period/Follicular/Ovulation/Luteal/PMS per day-range rules
    - _Requirements: 4.1, 4.2_

  - [x] 5.2 Write property test for phase calculation correctness (Property 10)
    - **Property 10: Phase calculation correctness**
    - **Validates: Requirements 4.1, 4.2**

  - [x] 5.3 Expose `GET /cycle/phase` via API Gateway → cycle_tracker Lambda
    - Read `last_period_date` and `cycle_length_days` from `cyclesync-users`; call `calculate_phase`; return `{ phase, day_in_cycle }` or profile-completion prompt
    - _Requirements: 4.3, 4.4_

- [x] 6. mood_tracker Lambda
  - [x] 6.1 Implement `POST /mood` handler
    - Validate mood ∈ {"Happy","Sad","Angry"} and note ≤ 500 chars
    - `PutItem` on `cyclesync-mood-entries` (PK: `user_id`, SK: today's date) — natural upsert; store note as plaintext
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 6.2 Write property test for mood note length enforcement (Property 11)
    - **Property 11: Mood note length enforcement**
    - **Validates: Requirements 5.2**

  - [x] 6.3 Write property test for mood entry persistence round-trip (Property 12)
    - **Property 12: Mood entry persistence round-trip**
    - **Validates: Requirements 5.3**

  - [x] 6.4 Write property test for one mood entry per day (Property 13)
    - **Property 13: One mood entry per day (upsert invariant)**
    - **Validates: Requirements 5.4, 5.5**

  - [x] 6.5 Implement `GET /mood/today` and `GET /mood/history` handlers
    - Today: `GetItem` for `(user_id, today)` or return null
    - History: `Query` on `cyclesync-mood-entries` with `KeyConditionExpression` for last 30 days, `ScanIndexForward=False`
    - _Requirements: 5.6_

  - [x] 6.6 Write property test for mood history ordering and window (Property 14)
    - **Property 14: Mood history ordering and window**
    - **Validates: Requirements 5.6**

- [x] 7. Checkpoint — Ensure all cycle and mood tests pass, ask the user if questions arise.

- [x] 8. prediction_engine and recommendation_engine Lambdas
  - [x] 8.1 Implement `predict_mood(phase)` pure Python function in prediction_engine Lambda
    - Map Period→Sad, Follicular→Happy, Ovulation→Happy, Luteal/PMS→Angry
    - _Requirements: 6.1, 6.2_

  - [x] 8.2 Write property test for phase-to-mood prediction mapping (Property 15)
    - **Property 15: Phase-to-mood prediction mapping**
    - **Validates: Requirements 6.1**

  - [x] 8.3 Implement Content_Store admin endpoints in recommendation_engine Lambda
    - `GET /admin/content`: `Scan` with `ExclusiveStartKey` pagination
    - `POST /admin/content`: `PutItem` with generated UUID `item_id`
    - `PUT /admin/content/:id`: `UpdateItem` by `item_id`
    - `DELETE /admin/content/:id`: `UpdateItem` set `is_deleted = True` (soft-delete)
    - Validate description <= 80 chars, rating 1.0-5.0, category in {"Song","Movie","Poem","Digital Colouring"}, language is a non-empty BCP 47 code string
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 8.4 Write property test for content item validity invariant (Property 20)
    - **Property 20: Content item validity invariant**
    - **Validates: Requirements 8.5, 10.1**

  - [x] 8.5 Write property test for content CRUD round-trip (Property 21)
    - **Property 21: Content CRUD round-trip**
    - **Validates: Requirements 10.2**

  - [x] 8.6 Implement `get_recommendations(phase, active_mood, hobbies, language_preference)` function and `GET /recommendations` handler
    - Query `cyclesync-content-items` GSI `mood-tags-index`, filter `category` in hobbies, `language = language_preference`, and `is_deleted = false`
    - If results < 5 per category, fall back to items with `language = "en"` matching same mood/category filters
    - If still < 5, fall back to top-rated items in that category regardless of language
    - Return at most 5 per category
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [x] 8.7 Write property test for recommendation correctness (Property 19)
    - **Property 19: Recommendation correctness**
    - **Validates: Requirements 8.1, 8.2**

  - [x] 8.8 Write property test for deleted content excluded from recommendations (Property 22)
    - **Property 22: Deleted content excluded from recommendations**
    - **Validates: Requirements 10.3**

- [x] 9. dashboard Lambda
  - [x] 9.1 Implement `GET /dashboard` handler
    - Invoke cycle_tracker, prediction_engine, mood_tracker, recommendation_engine via boto3 `lambda.invoke` in sequence
    - Build `DashboardResponse` with phase, day_in_cycle, phase_message (≤ 100 chars), support_message (≤ 150 chars), predicted_mood, logged_mood, active_mood, recommendations
    - If profile incomplete, return partial response with profile-completion prompt
    - _Requirements: 9.1, 9.2, 9.3, 6.3, 6.4_

  - [x] 9.2 Write property test for phase explanatory message length (Property 16)
    - **Property 16: Phase explanatory message length**
    - **Validates: Requirements 6.3**

  - [x] 9.3 Write property test for phase support message length (Property 23)
    - **Property 23: Phase support message length**
    - **Validates: Requirements 9.2**

  - [x] 9.4 Write property test for logged mood takes priority (Property 17)
    - **Property 17: Logged mood takes priority on dashboard**
    - **Validates: Requirements 6.4**

- [x] 10. notification_service Lambda
  - [x] 10.1 Implement notification_service Lambda handler
    - Define `NOTIFICATION_MESSAGES` dict in the Lambda with at least 3 witty, personality-driven messages per phase pool (Period, Follicular, Ovulation, Luteal/PMS)
    - On invocation: scan `cyclesync-users` for `notifications_on = true`, check `cyclesync-notification-logs` for daily cap (max 3), compute phase, select a random message via `random.choice(NOTIFICATION_MESSAGES[phase])`, write notification record to `cyclesync-notifications` DynamoDB table, write to `cyclesync-notification-logs`
    - The Lambda can be triggered manually or by any external cron-like mechanism (e.g., a scheduled call outside AWS); no EventBridge Scheduler rules are required
    - Implement `GET /notifications/settings` and `PUT /notifications/settings` handlers (read/write `cyclesync-users`)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.8, 13.9, 13.10_

- [x] 11. Frontend SPA
  - [x] 11.1 Create responsive HTML/CSS shell with breakpoints covering 320px–1920px
    - Plain HTML/CSS/JS, no framework; serve locally (e.g., `python -m http.server`) or from any static host; no S3 or CloudFront configuration needed
    - _Requirements: 9.4_

  - [x] 11.2 Implement registration and login forms
    - Display inline validation errors for missing fields, short password, duplicate email
    - On successful login store the opaque session token in memory (not localStorage); attach as `Authorization: Bearer <token>` on all API calls
    - _Requirements: 1.1, 1.3, 1.4, 2.2_

  - [x] 11.2b Implement forgot password and reset password screens
    - Forgot password screen: email input + "Send Reset Code" button; calls `POST /auth/forgot-password`; always shows generic confirmation message
    - Reset password screen: verification code input + new password input (min 8 chars) + confirm password input; calls `POST /auth/confirm-forgot-password`; on success redirects to login with success message; on invalid/expired code shows error with option to resend
    - _Requirements: 2b.1, 2b.2, 2b.3, 2b.4, 2b.5, 2b.6_

  - [x] 11.3 Implement Dashboard view consuming `GET /dashboard`
    - Render phase, active mood (with visual indicator distinguishing predicted vs logged), support message, and recommendation cards (title, category label, description)
    - Show profile-completion prompt when phase data is unavailable
    - _Requirements: 9.1, 9.2, 9.3, 6.3, 6.4, 4.4_

  - [x] 11.4 Implement mood logging form and mood history view
    - Mood form: three-option selector + optional note field (500-char limit); wire to `POST /mood`
    - History view: fetch `GET /mood/history`, render in reverse chronological order
    - _Requirements: 5.1, 5.2, 5.5, 5.6_

  - [x] 11.5 Implement profile and hobby preference settings screens
    - Wire to `PUT /profile` and `PUT /profile/hobbies`
    - Include language preference dropdown (English, Hindi, Tamil, Spanish) wired to `PUT /profile`
    - _Requirements: 3.1, 7.1, 7.2, 7.3, 7.4, 7.6, 7.7_

- [x] 12. Final checkpoint — Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests use **Hypothesis** (`@given`, `@settings(max_examples=100)`); each test must be tagged `# Feature: cycle-sync, Property N: <property_text>`
- All Lambda functions target Python 3.12 runtime; use `moto` for DynamoDB mocking in tests
- Checkpoints ensure incremental validation before moving to the next layer
