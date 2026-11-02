from ai_service import generate_quiz
from database import save_quiz_session


def create_topic_quiz(subject, goal, topic, knowledge_level="Beginner"):
    return generate_quiz(
        subject=subject,
        goal=goal,
        topic=topic,
        knowledge_level=knowledge_level,
    )


def submit_quiz_attempt(
    plan_id,
    topic,
    questions,
    selected_indices,
):
    return save_quiz_session(
        plan_id=plan_id,
        topic=topic,
        questions=questions,
        selected_indices=selected_indices,
    )