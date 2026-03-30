"""prediction_engine Lambda handler."""
import json

# Phase-to-mood mapping (Requirements 6.1)
_PHASE_MOOD_MAP = {
    "Period": "Sad",
    "Follicular": "Happy",
    "Ovulation": "Happy",
    "Luteal/PMS": "Angry",
}


def predict_mood(phase: str) -> str:
    """Pure function: map a cycle phase to a predicted mood.

    Args:
        phase: One of "Period", "Follicular", "Ovulation", "Luteal/PMS".

    Returns:
        Predicted mood string ("Sad", "Happy", or "Angry").

    Raises:
        ValueError: If phase is not a recognised cycle phase.
    """
    if phase not in _PHASE_MOOD_MAP:
        raise ValueError(
            f"Unknown phase {phase!r}. Expected one of {list(_PHASE_MOOD_MAP)}"
        )
    return _PHASE_MOOD_MAP[phase]


def lambda_handler(event, context):
    """Handle both direct Lambda invocation and API Gateway proxy events."""
    # Direct invocation from dashboard Lambda: {"phase": "Follicular"}
    if "phase" in event:
        phase = event["phase"]
        try:
            mood = predict_mood(phase)
        except ValueError as exc:
            return {"error": str(exc)}
        return {"predicted_mood": mood}

    # API Gateway proxy event
    try:
        body = json.loads(event.get("body") or "{}")
        phase = body.get("phase") or (event.get("queryStringParameters") or {}).get("phase")
        if not phase:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "phase", "message": "phase is required"}),
            }
        mood = predict_mood(phase)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"predicted_mood": mood}),
        }
    except ValueError as exc:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "phase", "message": str(exc)}),
        }
