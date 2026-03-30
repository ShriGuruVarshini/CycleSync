# CycleSync 🌸

> *Understand your cycle. Embrace your mood. Live in sync.*

CycleSync is a web application that helps women understand how their menstrual cycle affects their mood, provides personalised emotional support, and recommends hobby-based content — songs, movies, poetry, and digital colouring — tailored to how they feel today.

---

## What it does

Every day your body is in a different phase of its cycle. CycleSync tracks that phase, predicts how you might be feeling, and meets you where you are — with a warm message, a mood check-in, and hobby suggestions that actually match your energy.

- **Cycle Phase Tracking** — Calculates your current phase (Period, Follicular, Ovulation, Luteal/PMS) from your last period date and cycle length
- **Mood Prediction** — Predicts your mood based on your phase using a science-backed mapping
- **Mood Logging** — Log how you actually feel each day and track your history over 30 days
- **Personalised Nudges** — If you're feeling sad or angry, CycleSync notices and gently nudges you toward your favourite hobbies
- **Smart Recommendations** — Content suggestions (songs, movies, poetry, digital colouring) filtered by your mood, hobbies, and language preference
- **Notifications** — Phase-aware, witty daily notifications to keep you emotionally supported

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Plain HTML / CSS / JavaScript (no framework) |
| Backend | Python 3.12 AWS Lambda functions |
| Database | Amazon DynamoDB |
| Infrastructure | AWS SAM (`template.yaml`) |
| Auth | DynamoDB-backed JWT session tokens (bcrypt passwords) |
| Testing | Hypothesis (property-based) + pytest + moto |
| Local dev | Flask dev server with moto in-memory DynamoDB |

---

## Project structure

```
cycle_sync/
├── frontend/               # SPA — HTML, CSS, JS
│   ├── index.html
│   ├── css/styles.css
│   └── js/app.js
├── lambdas/
│   ├── auth/               # Register, login, logout, profile, hobbies
│   ├── cycle_tracker/      # Phase calculation
│   ├── mood_tracker/       # Mood logging and history
│   ├── prediction_engine/  # Phase → mood prediction
│   ├── recommendation_engine/ # Content recommendations + admin CRUD
│   ├── dashboard/          # Orchestrates all services
│   └── notification_service/  # Phase-aware notifications
├── layers/common/          # Shared utilities
├── scripts/
│   ├── local_server.py     # Local dev server (Flask + moto)
│   └── seed_config.py      # Seeds JWT secret to DynamoDB
└── template.yaml           # AWS SAM infrastructure definition
```

---

## Running locally

No AWS account needed. Everything runs in-memory.

**1. Install dependencies**

```bash
pip install flask boto3 "moto[dynamodb]" bcrypt hypothesis pytest
```

**2. Start the server**

```bash
python scripts/local_server.py
```

**3. Open the app**

```
http://localhost:5000
```

The server boots with a pre-seeded test user (Follicular phase, Day 11) and lands directly on the dashboard — no login required in local mode.

---

## Running tests

```bash
# Cycle tracker
python -m pytest "lambdas/cycle_tracker/tests/test_calculate_phase.py" -v

# Prediction engine
python -m pytest "lambdas/prediction_engine/tests/" -v

# Dashboard messages
python -m pytest "lambdas/dashboard/tests/" -v

# Auth property tests
python -m pytest "lambdas/auth/tests/" -v

# Mood tracker
python -m pytest "lambdas/mood_tracker/tests/" -v

# Recommendation engine
python -m pytest "lambdas/recommendation_engine/tests/test_property_content_validity.py" \
                 "lambdas/recommendation_engine/tests/test_property_recommendation_correctness.py" \
                 "lambdas/recommendation_engine/tests/test_property_deleted_content_excluded.py" -v
```

All property tests use [Hypothesis](https://hypothesis.readthedocs.io/) with 100 examples each.

---

## Deploying to AWS

**1. Install AWS SAM CLI**

```bash
# https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
```

**2. Build and deploy**

```bash
sam build
sam deploy --guided
```

**3. Seed the JWT secret**

```bash
python scripts/seed_config.py --env dev --region us-east-1
```

---

## Cycle phases

| Days | Phase | Predicted Mood |
|---|---|---|
| 1–5 | Period | Sad |
| 6–13 | Follicular | Happy |
| 14–16 | Ovulation | Happy |
| 17–end | Luteal / PMS | Angry |

---

## Hobby categories

Songs 🎵 · Movies 🎬 · Poetry 📖 · Digital Colouring 🎨

Content is filtered by your active mood, selected hobbies, and language preference (English, Hindi, Tamil, Spanish).

---

## License

MIT
