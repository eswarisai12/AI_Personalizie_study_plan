import streamlit as st
from dotenv import load_dotenv

from ai_service import AIServiceError, is_gemini_enabled
from database import (
    get_plan,
    get_plans,
    get_topic_stats,
    get_quiz_sessions,
    init_db,
)
from learning_plan import create_study_plan
from quiz_manager import create_topic_quiz, submit_quiz_attempt


load_dotenv()
init_db()

st.set_page_config(page_title="AI Learning Coach", page_icon="📚", layout="wide")


def plan_label(plan):
    return "{} — {} ({})".format(plan["subject"], plan["goal"], plan["created_at"][:10])


def render_plan(plan):
    st.subheader("Your study plan")
    if plan.get("generation_notice"):
        st.warning(plan["generation_notice"])
    st.write(plan["overview"])

    for week in plan["weeks"]:
        with st.expander("Week {}: {}".format(week["week_number"], week["focus"]), expanded=True):
            for topic in week["topics"]:
                st.markdown("#### {}".format(topic["name"]))
                estimated_minutes = topic.get("estimated_duration_minutes")
                if estimated_minutes is None:
                    st.caption("Estimated duration was not saved for this topic.")
                else:
                    st.caption("Estimated duration: {} minutes".format(estimated_minutes))
                st.markdown("**Learning objectives**")
                for objective in topic["objectives"]:
                    st.markdown("- {}".format(objective))
                st.markdown("**Key points**")
                for key_point in topic["key_points"]:
                    st.markdown("- {}".format(key_point))
                st.markdown("**Suggested activities**")
                for activity in topic["activities"]:
                    st.markdown("- {}".format(activity))


def render_quiz(plan_record, study_plan):
    topic_lookup = {}
    topic_labels = {}
    for week in study_plan["weeks"]:
        for topic_index, topic in enumerate(week["topics"]):
            topic_key = "{}:{}".format(week["week_number"], topic_index)
            topic_lookup[topic_key] = topic
            topic_labels[topic_key] = "Week {}: {}".format(week["week_number"], topic["name"])

    topic_keys = list(topic_lookup)
    selected_topic_key = st.selectbox(
        "Choose a topic",
        topic_keys,
        format_func=lambda key: topic_labels[key],
    )
    selected_topic = topic_lookup[selected_topic_key]
    quiz_state_key = "active_quiz"
    result_state_key = "last_quiz_result"
    generation_error_key = "quiz_generation_error"

    generate_requested = st.button(
        "Generate practice quiz",
        key="generate_quiz_{}".format(plan_record["id"]),
    )
    retry_requested = False
    generation_error = st.session_state.get(generation_error_key)
    if generation_error:
        retry_requested = st.button(
            "Retry quiz generation",
            key="retry_quiz_{}".format(plan_record["id"]),
        )
        if not retry_requested:
            st.error(generation_error)

    if generate_requested or retry_requested:
        st.session_state.pop(quiz_state_key, None)
        st.session_state.pop(result_state_key, None)
        st.session_state.pop(generation_error_key, None)
        try:
            quiz = create_topic_quiz(
                subject=plan_record["subject"],
                goal=plan_record["goal"],
                topic=selected_topic,
                knowledge_level=plan_record["knowledge_level"],
            )
        except AIServiceError as error:
            st.session_state[generation_error_key] = (
                "{} You can retry quiz generation when the service is available."
                .format(error)
            )
            st.rerun()
        else:
            quiz["topic_key"] = selected_topic_key
            quiz["plan_id"] = plan_record["id"]
            quiz["sequence"] = st.session_state.get("quiz_sequence", 0) + 1
            quiz["question_index"] = 0
            quiz["selected_indices"] = [None] * len(quiz["questions"])
            st.session_state["quiz_sequence"] = quiz["sequence"]
            st.session_state[quiz_state_key] = quiz

    quiz = st.session_state.get(quiz_state_key)
    if (
        quiz
        and quiz["plan_id"] == plan_record["id"]
        and quiz["topic_key"] == selected_topic_key
    ):
        question_index = quiz["question_index"]
        question = quiz["questions"][question_index]
        st.markdown("#### Practice quiz")
        st.progress(
            (question_index + 1) / len(quiz["questions"]),
            text="Question {} of {}".format(question_index + 1, len(quiz["questions"])),
        )
        st.write(question["question"])
        selected_answer = st.radio(
            "Choose an answer",
            question["choices"],
            index=None,
            key="quiz_answer_{}_{}_{}".format(
                plan_record["id"], quiz["sequence"], question_index
            ),
            label_visibility="collapsed",
        )
        if selected_answer is not None:
            selected_index = question["choices"].index(selected_answer)
            quiz["selected_indices"][question_index] = selected_index
            if selected_index == question["correct_answer"]:
                st.success("Correct! {}".format(question["explanation"]))
            else:
                st.error(
                    "Not quite. Correct answer: {}".format(
                        question["choices"][question["correct_answer"]]
                    )
                )
                st.write(question["explanation"])

            is_last_question = question_index == len(quiz["questions"]) - 1
            button_label = "Finish quiz" if is_last_question else "Next question"
            if st.button(
                button_label,
                key="quiz_next_{}_{}_{}".format(
                    plan_record["id"], quiz["sequence"], question_index
                ),
            ):
                if is_last_question:
                    try:
                        result = submit_quiz_attempt(
                            plan_id=plan_record["id"],
                            topic=selected_topic["name"],
                            questions=quiz["questions"],
                            selected_indices=quiz["selected_indices"],
                        )
                    except ValueError as error:
                        st.error(str(error))
                    else:
                        result["answers"] = [
                            dict(
                                question=question_data["question"],
                                selected_answer=question_data["choices"][answer_index],
                                correct_answer=question_data["choices"][
                                    question_data["correct_answer"]
                                ],
                                is_correct=(
                                    answer_index == question_data["correct_answer"]
                                ),
                                explanation=question_data["explanation"],
                            )
                            for question_data, answer_index in zip(
                                quiz["questions"], quiz["selected_indices"]
                            )
                        ]
                        st.session_state[result_state_key] = result
                        st.session_state.pop(quiz_state_key, None)
                else:
                    quiz["question_index"] += 1
                    st.rerun()

    result = st.session_state.get(result_state_key)
    if result and result["plan_id"] == plan_record["id"]:
        st.subheader(
            "Quiz score: {}/{} ({:.0%})".format(
                result["correct_count"], result["total_questions"], result["score"]
            )
        )
        for question_number, answer in enumerate(result["answers"], start=1):
            st.markdown("**Question {}**: {}".format(question_number, answer["question"]))
            if answer["is_correct"]:
                st.success(
                    "Correct! Answer: {}\n\n{}".format(
                        answer["correct_answer"], answer["explanation"]
                    )
                )
            else:
                st.error(
                    "Wrong answer. Correct answer: {}".format(answer["correct_answer"])
                )
                st.write(answer["explanation"])


def render_create_plan():
    st.title("Create your personalized study plan")
    st.write(
        "Tell the coach what you want to learn, what you already know, and how much "
        "time you can study. It will turn that into weekly goals and practice quizzes."
    )
    if not is_gemini_enabled():
        st.info(
            "Demo mode is active: plans and quizzes use local templates. Add a Gemini "
            "API key to generate subject-specific content."
        )

    with st.form("create_plan_form"):
        subject = st.text_input("Subject", placeholder="For example, biology or Python")
        goal = st.text_area(
            "What do you want to achieve?",
            placeholder="For example, understand the basics of Python and build a small project",
        )
        knowledge_level = st.selectbox(
            "Current knowledge level",
            ["Beginner", "Intermediate", "Advanced"],
        )
        duration_weeks = st.slider("Target duration (weeks)", 1, 12, 4)
        daily_minutes = st.slider("Study time per day (minutes)", 15, 180, 45, step=15)
        submitted = st.form_submit_button("Create my study plan")

    if submitted:
        if not subject.strip() or not goal.strip():
            st.error("Please enter both a subject and a learning goal.")
        else:
            try:
                plan_id = create_study_plan(
                    subject=subject.strip(),
                    goal=goal.strip(),
                    knowledge_level=knowledge_level,
                    duration_weeks=duration_weeks,
                    daily_minutes=daily_minutes,
                )
            except AIServiceError as error:
                st.error(str(error))
            else:
                st.session_state["selected_plan_id"] = plan_id
                st.success("Your study plan has been saved.")
                st.rerun()

    plan_id = st.session_state.get("selected_plan_id")
    if plan_id is not None:
        plan = get_plan(plan_id)
        if plan:
            study_plan = plan["plan"]
            render_plan(study_plan)
            st.divider()
            st.subheader("Practice")
            st.caption(
                "Answer all five questions about {} to see your quiz score and feedback."
                .format(plan["subject"])
            )
            render_quiz(plan, study_plan)


def render_dashboard():
    st.title("Your learning dashboard")
    plans = get_plans()
    if not plans:
        st.info("Create a study plan to start tracking your progress.")
        return

    plan_ids = [plan["id"] for plan in plans]
    default_plan_id = st.session_state.get("selected_plan_id")
    default_index = plan_ids.index(default_plan_id) if default_plan_id in plan_ids else 0
    selected_plan_id = st.selectbox(
        "Study plan",
        plan_ids,
        index=default_index,
        format_func=lambda plan_id: plan_label(next(p for p in plans if p["id"] == plan_id)),
    )
    plan = get_plan(selected_plan_id)
    if not plan:
        st.error("The selected study plan could not be found.")
        return

    topic_stats = get_topic_stats(selected_plan_id)
    attempts = get_quiz_sessions(selected_plan_id)
    total_questions = sum(attempt["total_questions"] for attempt in attempts)
    total_correct = sum(attempt["correct_count"] for attempt in attempts)
    accuracy = total_correct / total_questions if total_questions else None
    first, second, third, fourth = st.columns(4)
    first.metric("Study plans", len(plans))
    second.metric("Quizzes completed", len(attempts))
    third.metric("Questions answered", total_questions)
    fourth.metric(
        "Overall performance",
        "{:.0%}".format(accuracy) if accuracy is not None else "—",
    )
    st.caption("Quiz totals and overall performance are for the selected study plan.")
    st.caption(
        "Quiz scores are progress indicators, not proof of mastery, especially "
        "when based on only a few questions."
    )

    with st.expander("View saved study plan", expanded=False):
        render_plan(plan["plan"])

    st.subheader("Topic progress")
    if topic_stats:
        for stat in topic_stats:
            st.progress(
                stat["accuracy"],
                text="{} — {:.0%} ({} question{})".format(
                    stat["topic"],
                    stat["accuracy"],
                    stat["attempt_count"],
                    "" if stat["attempt_count"] == 1 else "s",
                ),
            )
    else:
        st.info("No quiz results yet. Take a practice quiz to see topic-by-topic progress.")

    st.subheader("Recommended next steps")
    weak_topics = [stat for stat in topic_stats if stat["accuracy"] < 0.7]
    planned_topics = [
        topic
        for week in plan["plan"]["weeks"]
        for topic in week["topics"]
    ]
    if weak_topics:
        next_topic_name = min(weak_topics, key=lambda stat: stat["accuracy"])["topic"]
        next_topic = next(
            (topic for topic in planned_topics if topic["name"] == next_topic_name),
            None,
        )
        st.warning(
            "Revise {} before moving on.".format(next_topic_name)
        )
        if next_topic and next_topic["activities"]:
            st.write("Suggested activity: {}".format(next_topic["activities"][0]))
        elif next_topic and next_topic["key_points"]:
            st.write("Suggested activity: Review the key points for this topic.")
    else:
        attempted_topics = {stat["topic"] for stat in topic_stats}
        strong_topics = [stat for stat in topic_stats if stat["accuracy"] >= 0.8]
        next_topic = next(
            (topic for topic in planned_topics if topic["name"] not in attempted_topics),
            None,
        )
        if next_topic:
            if strong_topics:
                strong_names = ", ".join(stat["topic"] for stat in strong_topics)
                st.success(
                    "Strong quiz performance on {}. Move forward to {}."
                    .format(strong_names, next_topic["name"])
                )
            elif topic_stats:
                st.success(
                    "Your attempted topics are at or above 70%. Continue with {}."
                    .format(next_topic["name"])
                )
            else:
                st.write("Start with {}.".format(next_topic["name"]))
            if next_topic["activities"]:
                st.write("Suggested activity: {}".format(next_topic["activities"][0]))
            else:
                st.write("Suggested activity: Take a practice quiz on this topic.")
        elif strong_topics:
            strongest_topic = max(strong_topics, key=lambda stat: stat["accuracy"])
            st.success(
                "Strong performance across the planned topics. Try harder practice "
                "or apply {} in a new problem."
                .format(strongest_topic["topic"])
            )
        elif planned_topics:
            st.info(
                "You have practiced every planned topic. Keep practicing to build "
                "confidence before moving on."
            )
        else:
            st.info("This study plan does not contain any topics to recommend.")

    st.subheader("Recent quiz history")
    if attempts:
        for attempt in attempts:
            with st.expander(
                "Quiz {} — {}/{} ({:.0%}) — {}".format(
                    attempt["attempt_number"],
                    attempt["correct_count"],
                    attempt["total_questions"],
                    attempt["score"],
                    attempt["created_at"],
                )
            ):
                st.write("Topic: {}".format(attempt["topic"]))
                for question_number, answer in enumerate(attempt["answers"], start=1):
                    st.markdown(
                        "**Question {}**: {}".format(question_number, answer["question"])
                    )
                    if answer["is_correct"]:
                        st.success("Correct — {}".format(answer["explanation"]))
                    else:
                        st.error("Wrong — correct answer: {}".format(answer["correct_answer"]))
                        st.write(answer["explanation"])
    else:
        st.write("Your quiz attempts will appear here.")


st.sidebar.title("AI Learning Coach")
page = st.sidebar.radio("Navigate", ["Create a study plan", "My dashboard"])
if is_gemini_enabled():
    st.sidebar.caption("Gemini is configured")
else:
    st.sidebar.caption("Local demo mode")

if page == "Create a study plan":
    render_create_plan()
else:
    render_dashboard()
