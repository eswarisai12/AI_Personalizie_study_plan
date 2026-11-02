import json
import os
import tempfile
from pathlib import Path

from ai_service import AIServiceError, generate_study_plan
from database import save_plan


EXAMPLE_PLAN_PATH = Path(__file__).with_name("sample_data") / "example_learning_plan.json"


def _write_latest_plan(plan):
    EXAMPLE_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(EXAMPLE_PLAN_PATH.parent),
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(plan, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
        os.replace(str(temporary_path), str(EXAMPLE_PLAN_PATH))
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def create_study_plan(subject, goal, knowledge_level, duration_weeks, daily_minutes):
    plan = generate_study_plan(
        subject=subject,
        goal=goal,
        knowledge_level=knowledge_level,
        duration_weeks=duration_weeks,
        daily_minutes=daily_minutes,
    )
    try:
        _write_latest_plan(plan)
    except OSError as error:
        raise AIServiceError(
            "The study plan could not be written to sample_data/example_learning_plan.json."
        ) from error
    return save_plan(
        goal=goal,
        subject=subject,
        knowledge_level=knowledge_level,
        duration_weeks=duration_weeks,
        daily_minutes=daily_minutes,
        plan=plan,
    )