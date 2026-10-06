"""Coordinate the steps that process one request's state.

Future phases add research and qualification here. Today this function marks
the application foundation ready and returns the same state to the API.
"""

from app.orchestration.state import OutreachState


async def run_workflow(state: OutreachState) -> OutreachState:
    """Mark the application foundation ready without running outreach steps."""
    # Update the progress of the record supplied by the API.
    state.current_step = "skeleton_ready"
    # Returning a state preserves the goal and any results already in it.
    return state
