# Requirements Document

## Introduction

CycleSync is a web-based application that helps women understand mood changes based on their menstrual cycle phase, provides personalized emotional support, and recommends hobby-based content (songs, movies, poetry, digital colouring). The MVP covers cycle tracking, mood tracking, and basic content recommendations. The system targets women aged 18-45, including working professionals and students interested in health tracking and lifestyle improvement.

## Glossary

- **CycleSync**: The web application described in this document
- **User**: A registered woman using the CycleSync application
- **Cycle_Tracker**: The component responsible for calculating and managing menstrual cycle phases
- **Mood_Tracker**: The component responsible for recording and storing daily mood entries
- **Prediction_Engine**: The component that predicts mood based on the current cycle phase
- **Recommendation_Engine**: The component that generates content suggestions based on phase, mood, and hobby preferences
- **Dashboard**: The main view presented to the User after login, showing phase, mood prediction, and recommendations
- **Content_Store**: The database of songs, movies, poetry, and digital colouring activities tagged by mood and category
- **Auth_Service**: The component responsible for user registration, login, and session management
- **Cycle_Phase**: One of four phases -- Period, Follicular, Ovulation, or Luteal/PMS -- calculated from the User's last period date and cycle length
- **Mood_Entry**: A daily log record containing a mood value (Happy, Sad, or Angry) and an optional text note
- **Hobby_Preference**: A User-selected interest category: Songs, Movies, Poems/Poetry, or Digital Colouring
- **Language_Preference**: The User's preferred content language (e.g., English, Hindi, Tamil, Spanish), stored as a BCP 47 language code (e.g., "en", "hi", "ta", "es"). Used to filter content recommendations; falls back to English when no matching content is available.
- **Notification_Service**: The component responsible for sending scheduled, phase-aware notifications to Users

---

## Requirements

### Requirement 1: User Registration

**User Story:** As a new visitor, I want to create an account, so that I can access personalized cycle and mood tracking features.

#### Acceptance Criteria

1. THE Auth_Service SHALL provide a registration form that collects a unique email address, a password, a display name, age, last period date, average cycle length in days, hobby preferences, and language preference.
2. WHEN a registration form is submitted with all required fields, THE Auth_Service SHALL create a new User account and redirect the User to the Dashboard.
3. IF a submitted email address already exists in the system, THEN THE Auth_Service SHALL return an error message stating that the email is already registered.
4. IF a submitted password is fewer than 8 characters, THEN THE Auth_Service SHALL return an error message stating the minimum password length requirement.
5. THE Auth_Service SHALL store passwords using a one-way cryptographic hash and SHALL NOT store plaintext passwords.

---

### Requirement 2: User Login and Session Management

**User Story:** As a registered User, I want to log in securely, so that I can access my personal data.

#### Acceptance Criteria

1. WHEN a User submits a valid email and password combination, THE Auth_Service SHALL authenticate the User and establish a session.
2. IF a User submits an invalid email or password, THEN THE Auth_Service SHALL return a generic error message without revealing which field is incorrect.
3. WHEN a User session has been inactive for 30 minutes, THE Auth_Service SHALL invalidate the session and require the User to log in again.
4. WHEN a User explicitly logs out, THE Auth_Service SHALL invalidate the session immediately.

---

### Requirement 2b: Forgot Password / Reset Password

**User Story:** As a registered User who has forgotten their password, I want to reset it via email, so that I can regain access to my account.

#### Acceptance Criteria

1. THE Auth_Service SHALL provide a "Forgot Password" option on the login screen.
2. WHEN a User submits their registered email address on the forgot password screen, THE Auth_Service SHALL trigger a Cognito ForgotPassword API call, which sends a verification code to the User's email.
3. IF the submitted email does not exist in the system, THEN THE Auth_Service SHALL return a generic message ("If this email is registered, you will receive a reset code") without revealing whether the email exists.
4. WHEN a User submits a valid verification code and a new password of at least 8 characters, THE Auth_Service SHALL call Cognito ConfirmForgotPassword and update the password.
5. IF the verification code is invalid or expired, THEN THE Auth_Service SHALL return an error message asking the User to request a new code.
6. WHEN a password reset is completed successfully, THE Auth_Service SHALL redirect the User to the login screen with a success message.

---

### Requirement 3: User Profile Management

**User Story:** As a registered User, I want to update my profile details, so that my cycle calculations and recommendations stay accurate.

#### Acceptance Criteria

1. THE Auth_Service SHALL allow a logged-in User to update display name, age, last period date, average cycle length, hobby preferences, and language preference.
2. WHEN a User saves updated profile data, THE Auth_Service SHALL persist the changes and confirm the update to the User within 2 seconds.
3. IF a User submits an average cycle length outside the range of 21 to 45 days, THEN THE Auth_Service SHALL return a validation error describing the accepted range.

---

### Requirement 4: Menstrual Cycle Phase Calculation

**User Story:** As a User, I want the app to calculate my current cycle phase, so that I can understand where I am in my cycle without manual effort.

#### Acceptance Criteria

1. WHEN a User's last period date and cycle length are available, THE Cycle_Tracker SHALL calculate the current Cycle_Phase using the formula: current day in cycle = (today - last period date) mod cycle length.
2. THE Cycle_Tracker SHALL map the current day in cycle to a Cycle_Phase according to the following rules:
   - Days 1-5: Period
   - Days 6-13: Follicular
   - Days 14-16: Ovulation
   - Days 17 to end of cycle: Luteal/PMS
3. WHEN the current Cycle_Phase is calculated, THE Cycle_Tracker SHALL make the result available to the Dashboard and Prediction_Engine within 500 milliseconds.
4. IF a User has not provided a last period date, THEN THE Cycle_Tracker SHALL display a prompt asking the User to complete their profile before showing phase information.

---

### Requirement 5: Mood Logging

**User Story:** As a User, I want to log my mood each day, so that I can track how I feel throughout my cycle.

#### Acceptance Criteria

1. THE Mood_Tracker SHALL present a daily mood entry form with three mood options: Happy, Sad, and Angry.
2. WHERE a User chooses to add context, THE Mood_Tracker SHALL accept an optional free-text note of up to 500 characters alongside the mood selection.
3. WHEN a User submits a Mood_Entry, THE Mood_Tracker SHALL persist the entry with a timestamp and confirm the save to the User within 2 seconds.
4. THE Mood_Tracker SHALL allow a User to submit one Mood_Entry per calendar day.
5. IF a User attempts to submit a second Mood_Entry on the same calendar day, THEN THE Mood_Tracker SHALL replace the existing entry with the new submission and notify the User that the previous entry has been updated.
6. THE Mood_Tracker SHALL display the User's mood history for the past 30 days in reverse chronological order.

---

### Requirement 6: Mood Prediction

**User Story:** As a User, I want to see a predicted mood for today based on my cycle phase, so that I can prepare emotionally for the day.

#### Acceptance Criteria

1. WHEN the current Cycle_Phase is known, THE Prediction_Engine SHALL produce a predicted mood for the current day using the following phase-to-mood mapping:
   - Period: Sad
   - Follicular: Happy
   - Ovulation: Happy
   - Luteal/PMS: Angry
2. THE Prediction_Engine SHALL make the predicted mood available to the Dashboard within 500 milliseconds of receiving the current Cycle_Phase.
3. THE Dashboard SHALL display the predicted mood alongside a short explanatory message of no more than 100 characters describing why that mood is associated with the current phase.
4. IF the User has logged an actual Mood_Entry for today, THE Dashboard SHALL display the logged mood as the primary mood and the predicted mood as a secondary reference.

---

### Requirement 7: Hobby Preference Management

**User Story:** As a User, I want to select my hobby interests and preferred content language, so that recommendations are relevant to what I enjoy and are in a language I understand.

#### Acceptance Criteria

1. THE Auth_Service SHALL present a hobby preference selection screen during registration and in the User profile settings.
2. THE Auth_Service SHALL offer the following Hobby_Preference options: Songs, Movies, Poems/Poetry, and Digital Colouring.
3. WHEN a User selects one or more Hobby_Preferences and saves, THE Auth_Service SHALL persist the selections and confirm the save within 2 seconds.
4. THE Auth_Service SHALL allow a User to select multiple Hobby_Preferences simultaneously.
5. IF a User has not selected any Hobby_Preference, THEN THE Recommendation_Engine SHALL use all four categories as the default preference set.
6. THE Auth_Service SHALL present a Language_Preference selection field during registration and in the User profile settings, offering at minimum the options: English, Hindi, Tamil, and Spanish.
7. WHEN a User selects a Language_Preference and saves, THE Auth_Service SHALL persist the selection and confirm the save within 2 seconds.

---

### Requirement 8: Content Recommendation

**User Story:** As a User, I want to receive content suggestions tailored to my current phase, mood, and preferred language, so that I can find comfort and enjoyment during each part of my cycle.

#### Acceptance Criteria

1. WHEN the current Cycle_Phase, the active mood (logged or predicted), and the User's Hobby_Preferences are available, THE Recommendation_Engine SHALL retrieve up to 5 content items per selected Hobby_Preference category from the Content_Store.
2. THE Recommendation_Engine SHALL select content items whose mood and category tags match the active mood and the User's Hobby_Preferences.
3. WHEN filtering content items, THE Recommendation_Engine SHALL prioritize items whose language attribute matches the User's Language_Preference.
4. IF no content items match the User's Language_Preference, THEN THE Recommendation_Engine SHALL fall back to content items with language "en" (English).
5. IF no tagged content items match the active mood and Hobby_Preferences, THEN THE Recommendation_Engine SHALL return the 5 highest-rated items in each selected Hobby_Preference category as default recommendations.
6. THE Recommendation_Engine SHALL deliver recommendations to the Dashboard within 2 seconds of receiving the required inputs.
7. THE Dashboard SHALL display each recommendation with a title, category label (Song / Movie / Poem / Digital Colouring), and a short description of no more than 80 characters.

---

### Requirement 9: Smart Daily Dashboard

**User Story:** As a User, I want a single view that shows my cycle phase, mood, and recommendations, so that I can get all relevant information at a glance.

#### Acceptance Criteria

1. WHEN a logged-in User opens the Dashboard, THE Dashboard SHALL display the current Cycle_Phase, the active mood, the predicted mood (if different from the active mood), and the content recommendations within 2 seconds.
2. THE Dashboard SHALL display a personalized emotional support message of no more than 150 characters based on the current Cycle_Phase.
3. WHEN a User has not logged a mood for today, THE Dashboard SHALL display the predicted mood with a visual indicator distinguishing it from a logged mood.
4. THE Dashboard SHALL be responsive and render correctly on screen widths from 320px to 1920px.

---

### Requirement 10: Content Management

**User Story:** As a system administrator, I want to manage the content library, so that Users always have relevant and up-to-date recommendations.

#### Acceptance Criteria

1. THE Content_Store SHALL store each content item with the following attributes: title, category (Song / Movie / Poem / Digital Colouring), mood tags (one or more of Happy / Sad / Angry), a short description of no more than 80 characters, a rating value between 1 and 5, and a language attribute (BCP 47 language code, e.g., "en", "hi", "ta", "es").
2. THE Content_Store SHALL support create, read, update, and delete operations for content items.
3. WHEN a content item is deleted, THE Recommendation_Engine SHALL exclude that item from all future recommendation results immediately.

---

### Requirement 11: Performance

**User Story:** As a User, I want the application to respond quickly, so that I am not frustrated by slow load times.

#### Acceptance Criteria

1. THE CycleSync SHALL return a fully rendered Dashboard to the User within 2 seconds under normal load conditions.
2. THE CycleSync SHALL support at least 100 concurrent Users without degrading response times beyond 2 seconds.

---

### Requirement 12: Security and Data Protection

**User Story:** As a User, I want my personal health data to be protected, so that my private information is not exposed.

#### Acceptance Criteria

1. THE Auth_Service SHALL transmit all data between the client and server over HTTPS.
2. THE CycleSync SHALL store User health data (cycle dates, mood entries) in an encrypted form at rest.
3. THE Auth_Service SHALL enforce session token expiry as defined in Requirement 2, Criterion 3.
4. THE CycleSync SHALL not expose another User's data through any API endpoint.

---

### Requirement 13: Smart Mood-Based Notifications

**User Story:** As a User, I want to receive witty, relatable, personality-driven notifications based on my cycle phase, so that I feel emotionally supported and engaged throughout my cycle.

#### Acceptance Criteria

1. WHEN the current Cycle_Phase is known, THE Notification_Service SHALL select a notification message at random from a phase-specific message library according to the following phase mapping:
   - Period phase: Period message pool
   - Follicular phase: Follicular message pool
   - Ovulation phase: Ovulation message pool
   - Luteal/PMS phase: Luteal/PMS message pool
2. THE Notification_Service SHALL maintain a message library containing at least 3 distinct personality-driven, witty, and relatable messages per Cycle_Phase pool (minimum 12 messages total across all four pools).
3. THE Notification_Service SHALL deliver no more than 3 notifications to a User per calendar day.
4. THE Notification_Service SHALL schedule notifications at the following times of day: morning (08:00), afternoon (13:00), and evening (20:00), using the User's local timezone.
5. WHEN a User has selected Songs as a Hobby_Preference and a notification is triggered, THE Notification_Service SHALL include a playlist suggestion in the notification body.
6. WHEN a User has selected Movies as a Hobby_Preference and a notification is triggered, THE Notification_Service SHALL include a comfort movie suggestion in the notification body.
7. WHEN a User has selected Poetry as a Hobby_Preference and a notification is triggered, THE Notification_Service SHALL include a relevant quote in the notification body.
8. THE Notification_Service SHALL allow a User to enable or disable all notifications from the User profile settings.
9. WHILE notifications are disabled by the User, THE Notification_Service SHALL not deliver any notifications to that User.
10. IF the Notification_Service fails to deliver a notification, THEN THE Notification_Service SHALL log the failure and SHALL NOT retry delivery for that scheduled notification slot.
