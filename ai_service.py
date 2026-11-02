import json
import os
import random
import time
from json import JSONDecodeError
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError


load_dotenv(Path(__file__).with_name(".env"))


class AIServiceError(Exception):
    """Raised when the configured AI service cannot return usable content."""


class GeminiQuotaError(AIServiceError):
    """Raised when Gemini rejects a request because its quota is exhausted."""


class GeminiConnectionError(AIServiceError):
    """Raised when a Gemini request fails before receiving an API response."""


def is_gemini_enabled():
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def is_gemini_quiz_enabled():
    if not is_gemini_enabled():
        return False
    return os.getenv("GEMINI_GENERATE_QUIZZES", "true").strip().lower() == "true"


def _generate_json(prompt):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise AIServiceError("Gemini is not configured. Add GEMINI_API_KEY to your .env file.")

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.4,
                },
            )
            break
        except APIError as error:
            if error.code == 429:
                raise GeminiQuotaError(
                    "Gemini's request quota has been reached."
                ) from error
            if error.code == 503 and attempt < 2:
                time.sleep(attempt + 1)
                continue
            if error.code == 503:
                raise AIServiceError(
                    "Gemini is temporarily busy (503). Please wait a minute and try again."
                ) from error
            raise AIServiceError("Gemini request failed: {}".format(error)) from error
        except httpx.TransportError as error:
            raise GeminiConnectionError(
                "Gemini could not be reached. Check your internet connection and try again."
            ) from error

    if not response.text:
        raise AIServiceError("Gemini returned an empty response. Please try again.")
    try:
        result = json.loads(response.text)
    except JSONDecodeError as error:
        raise AIServiceError("Gemini returned invalid JSON. Please try again.") from error
    if not isinstance(result, dict):
        raise AIServiceError("Gemini returned an unexpected response format. Please try again.")
    return result


def _required_text(data, field, context):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AIServiceError("Gemini returned an invalid {} in {}.".format(field, context))
    return value.strip()


def _required_text_list(data, field, context):
    value = data.get(field)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise AIServiceError("Gemini returned an invalid {} in {}.".format(field, context))
    return [item.strip() for item in value]


def _local_study_plan(subject, goal, knowledge_level, duration_weeks, daily_minutes):
    phases = [
        "Build a foundation",
        "Learn core concepts",
        "Connect related ideas",
        "Practice with examples",
        "Apply your knowledge",
        "Review and consolidate",
    ]
    weeks = []
    for week_number in range(1, duration_weeks + 1):
        focus = phases[(week_number - 1) % len(phases)]
        topic_name = "{}: {}".format(subject, focus.lower())
        weeks.append(
            {
                "week_number": week_number,
                "focus": focus,
                "topics": [
                    {
                        "name": topic_name,
                        "estimated_duration_minutes": daily_minutes * 7,
                        "objectives": [
                            "Identify the ideas in {} that are most relevant to: {}.".format(
                                subject, goal
                            ),
                            "Build on your {} starting point with a small, measurable learning goal.".format(
                                knowledge_level.lower()
                            ),
                        ],
                        "key_points": [
                            "Explain one important idea from {} in your own words.".format(subject),
                            "Connect a concept you studied to your goal: {}.".format(goal),
                        ],
                        "activities": [
                            "Study for about {} minutes each day, adjusting the pace when needed.".format(
                                daily_minutes
                            ),
                            "Finish each study session with a short recall exercise and note one question to revisit.",
                        ],
                    }
                ],
            }
        )
    return {
        "overview": (
            "A {}-week demo plan for {}. It starts from your {} level and builds toward: {}. "
            "The weekly activities are sized around {} minutes of study per day. Add a Gemini "
            "API key for subject-specific AI-generated content."
        ).format(duration_weeks, subject, knowledge_level.lower(), goal, daily_minutes),
        "weeks": weeks,
    }


def _validate_plan(data, duration_weeks, daily_minutes):
    overview = _required_text(data, "overview", "the study plan")
    weekly_time_budget = daily_minutes * 7
    raw_weeks = data.get("weeks")
    if not isinstance(raw_weeks, list) or len(raw_weeks) != duration_weeks:
        raise AIServiceError(
            "Gemini returned an unexpected number of study weeks. Please generate the plan again."
        )

    weeks = []
    for expected_week, raw_week in enumerate(raw_weeks, start=1):
        if not isinstance(raw_week, dict):
            raise AIServiceError("Gemini returned an invalid study week.")
        raw_number = raw_week.get("week_number", expected_week)
        if not isinstance(raw_number, int) or raw_number != expected_week:
            raise AIServiceError("Gemini returned study weeks in an invalid order.")
        raw_topics = raw_week.get("topics")
        if not isinstance(raw_topics, list) or not raw_topics:
            raise AIServiceError("Gemini returned a study week without any topics.")

        topics = []
        week_duration = 0
        for raw_topic in raw_topics:
            if not isinstance(raw_topic, dict):
                raise AIServiceError("Gemini returned an invalid study topic.")
            estimated_duration = raw_topic.get("estimated_duration_minutes")
            if (
                not isinstance(estimated_duration, int)
                or isinstance(estimated_duration, bool)
                or estimated_duration <= 0
            ):
                raise AIServiceError(
                    "Gemini returned an invalid estimated topic duration."
                )
            week_duration += estimated_duration
            topics.append(
                {
                    "name": _required_text(raw_topic, "name", "a study topic"),
                    "estimated_duration_minutes": estimated_duration,
                    "objectives": _required_text_list(raw_topic, "objectives", "a study topic"),
                    "key_points": _required_text_list(raw_topic, "key_points", "a study topic"),
                    "activities": _required_text_list(raw_topic, "activities", "a study topic"),
                }
            )
        if week_duration > weekly_time_budget:
            raise AIServiceError(
                "Gemini returned topic durations that exceed the available weekly study time."
            )
        weeks.append(
            {
                "week_number": expected_week,
                "focus": _required_text(raw_week, "focus", "a study week"),
                "topics": topics,
            }
        )
    return {"overview": overview, "weeks": weeks}


def generate_study_plan(subject, goal, knowledge_level, duration_weeks, daily_minutes):
    if not is_gemini_enabled():
        return _local_study_plan(subject, goal, knowledge_level, duration_weeks, daily_minutes)

    prompt = """
Create a practical, personalized study plan as JSON only.
Student's subject: {subject}
Learning goal: {goal}
Current knowledge level: {knowledge_level}
Duration: exactly {duration_weeks} weeks
Available study time: {daily_minutes} minutes per day

Return this shape:
{{
  "overview": "brief personalized summary",
  "weeks": [
    {{
      "week_number": 1,
      "focus": "weekly focus",
      "topics": [
        {{
          "name": "specific topic",
          "estimated_duration_minutes": 180,
          "objectives": ["measurable objective"],
          "key_points": ["important concept"],
          "activities": ["time-aware study activity"]
        }}
      ]
    }}
  ]
}}

Include one to three relevant topics per week, with two or three concise objectives,
key points, and activities per topic. Give each topic a positive integer
estimated_duration_minutes. The sum of a week's topic durations must not exceed
{weekly_time_budget} minutes (the learner's daily time multiplied by seven). Respect
the learner's current level, goal, target duration, and daily time. Number weeks
consecutively starting at 1.
""".format(
        subject=subject,
        goal=goal,
        knowledge_level=knowledge_level,
        duration_weeks=duration_weeks,
        daily_minutes=daily_minutes,
        weekly_time_budget=daily_minutes * 7,
    )
    try:
        return _validate_plan(_generate_json(prompt), duration_weeks, daily_minutes)
    except (GeminiQuotaError, GeminiConnectionError) as error:
        plan = _local_study_plan(
            subject, goal, knowledge_level, duration_weeks, daily_minutes
        )
        plan["generation_notice"] = (
            "{} A local template plan is shown so you can continue.".format(error)
        )
        return plan


def _local_quiz(subject, goal, topic, knowledge_level="Beginner"):
    normalized_subject = " ".join(subject.casefold().split())
    if normalized_subject in {"python", "python programming", "programming in python"}:
        question_bank = [
            {
                "question": "What does this Python code print?\n\nvalue = 4\nprint(value * 2)",
                "choices": ["8", "42", "4", "value * 2"],
                "correct_answer": 0,
                "explanation": "The multiplication is evaluated first, so 4 * 2 is 8.",
                "advanced_explanation": "Python applies multiplication before calling print, so the expression evaluates to 8.",
            },
            {
                "question": "What does the Python keyword `def` do?",
                "choices": [
                    "Defines a function",
                    "Repeats a block of code",
                    "Imports a module",
                    "Returns a value from a function",
                ],
                "correct_answer": 0,
                "explanation": "A `def` statement defines a function that can be called later.",
                "advanced_explanation": "Executing a `def` statement creates a function object and binds it to the declared name; the body runs when called.",
            },
            {
                "question": "What does this Python code print?\n\nfor number in range(3):\n    print(number)",
                "choices": ["0, 1, 2", "1, 2, 3", "0, 1, 2, 3", "3"],
                "correct_answer": 0,
                "explanation": "`range(3)` produces 0, 1, and 2, and the loop prints each value.",
                "advanced_explanation": "`range(3)` is a half-open sequence starting at 0 and stopping before 3, so the loop prints 0, 1, and 2.",
            },
            {
                "question": "What does the Python keyword `return` do inside a function?",
                "choices": [
                    "Sends a value back to the code that called the function",
                    "Repeats the function forever",
                    "Creates a new variable",
                    "Displays a value on the screen automatically",
                ],
                "correct_answer": 0,
                "explanation": "`return` ends the function and provides its result to the caller.",
                "advanced_explanation": "`return` exits the current function call and sends its expression value back to the caller.",
            },
            {
                "question": "What does this Python expression evaluate to?\n\n[10, 20, 30][1]",
                "choices": ["20", "10", "30", "1"],
                "correct_answer": 0,
                "explanation": "Python list indexes start at 0, so index 1 refers to the second item.",
                "advanced_explanation": "Python sequences use zero-based indexing, making index 1 the element at offset one: 20.",
            },
            {
                "question": "What is the purpose of the Python keyword `if`?",
                "choices": [
                    "Run a block only when a condition is true",
                    "Define a function",
                    "Repeat a block for every item in a sequence",
                    "Stop the Python program",
                ],
                "correct_answer": 0,
                "explanation": "An `if` statement runs its indented block when its condition is true.",
                "advanced_explanation": "An `if` statement evaluates its condition's truth value and executes the suite only when that value is true.",
            },
        ]
    elif normalized_subject in {"physics", "basic physics", "physics basics", "physics fundamentals"}:
        question_bank = [
            {
                "question": "A runner travels 100 metres in 20 seconds. What is the runner's average speed?",
                "choices": ["5 m/s", "20 m/s", "80 m/s", "2,000 m/s"],
                "correct_answer": 0,
                "explanation": "Average speed is distance divided by time: 100 m / 20 s = 5 m/s.",
                "advanced_explanation": "Using v_avg = Δx/Δt, 100 m / 20 s = 5 m·s⁻¹.",
            },
            {
                "question": "What net force is needed to accelerate a 2 kg object at 3 m/s²?",
                "choices": ["6 N", "1.5 N", "5 N", "9 N"],
                "correct_answer": 0,
                "explanation": "Newton's second law gives F = ma = 2 kg × 3 m/s² = 6 N.",
                "advanced_explanation": "Newton's second law, ΣF = ma, gives a net force of 2 kg × 3 m·s⁻² = 6 N.",
            },
            {
                "question": "Which unit is used to measure energy in the SI system?",
                "choices": ["Joule", "Newton", "Watt", "Pascal"],
                "correct_answer": 0,
                "explanation": "Energy is measured in joules (J).",
                "advanced_explanation": "The SI derived unit of energy is the joule: 1 J = 1 kg·m²·s⁻².",
            },
            {
                "question": "If the same force acts on an object with twice the mass, what happens to its acceleration?",
                "choices": [
                    "It becomes half as large",
                    "It doubles",
                    "It stays the same",
                    "It becomes four times as large",
                ],
                "correct_answer": 0,
                "explanation": "From a = F/m, doubling mass while keeping force constant halves acceleration.",
                "advanced_explanation": "For fixed net force, Newton's second law gives a = F/m; doubling m therefore halves a.",
            },
            {
                "question": "A 12 V battery is connected across a 4 Ω resistor. What current flows?",
                "choices": ["3 A", "48 A", "8 A", "0.33 A"],
                "correct_answer": 0,
                "explanation": "Ohm's law gives I = V/R = 12 V / 4 Ω = 3 A.",
                "advanced_explanation": "Applying Ohm's law, I = V/R = 12/4 = 3 A; the units reduce to amperes.",
            },
            {
                "question": "What is the approximate acceleration due to gravity near Earth's surface?",
                "choices": ["9.8 m/s² downward", "9.8 m/s upward", "0 m/s²", "98 m/s² upward"],
                "correct_answer": 0,
                "explanation": "Near Earth's surface, gravitational acceleration is about 9.8 m/s² downward.",
                "advanced_explanation": "The near-surface gravitational field strength is approximately g = 9.8 m·s⁻², directed toward Earth's center.",
            },
            {
                "question": "A wave has a frequency of 5 Hz and a wavelength of 2 m. What is its speed?",
                "choices": ["10 m/s", "2.5 m/s", "7 m/s", "0.4 m/s"],
                "correct_answer": 0,
                "explanation": "Wave speed is frequency × wavelength: 5 Hz × 2 m = 10 m/s.",
                "advanced_explanation": "Using v = fλ, the propagation speed is 5 s⁻¹ × 2 m = 10 m·s⁻¹.",
            },
            {
                "question": "What happens to the gravitational potential energy of an object when it is lifted higher?",
                "choices": [
                    "It increases",
                    "It decreases to zero",
                    "It stays constant in all cases",
                    "It changes into electric charge",
                ],
                "correct_answer": 0,
                "explanation": "Near Earth's surface, gravitational potential energy increases with height.",
                "advanced_explanation": "Near Earth's surface, U_g = mgh; increasing height increases gravitational potential energy for fixed mass and g.",
            },
        ]
    else:
        raise AIServiceError(
            "Local quizzes are currently available for Python and Physics. To create "
            "questions for '{}', configure Gemini and set GEMINI_GENERATE_QUIZZES=true."
            .format(subject)
        )
    questions = [
        dict(question, choices=list(question["choices"]))
        for question in random.sample(question_bank, 5)
    ]
    for question in questions:
        if knowledge_level.casefold() == "advanced":
            question["explanation"] = question.get(
                "advanced_explanation", question["explanation"]
            )
        question.pop("advanced_explanation", None)
        correct_choice = question["choices"][question["correct_answer"]]
        random.shuffle(question["choices"])
        question["correct_answer"] = question["choices"].index(correct_choice)
    return {"questions": questions}


def _validate_quiz(data):
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or len(raw_questions) != 5:
        raise AIServiceError("Gemini must return exactly five quiz questions.")

    questions = []
    seen_questions = set()
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            raise AIServiceError("Gemini returned an invalid quiz question.")
        question = _required_text(raw_question, "question", "the quiz")
        if question.casefold() in seen_questions:
            raise AIServiceError("Gemini returned duplicate quiz questions. Please try again.")
        seen_questions.add(question.casefold())

        choices = _required_text_list(raw_question, "choices", "the quiz")
        if len(choices) != 4 or len({choice.casefold() for choice in choices}) != 4:
            raise AIServiceError(
                "Each quiz question must have exactly four distinct answer choices."
            )
        correct_answer = raw_question.get("correct_answer")
        if (
            not isinstance(correct_answer, int)
            or isinstance(correct_answer, bool)
            or not 0 <= correct_answer < len(choices)
        ):
            raise AIServiceError("Gemini returned an invalid correct answer for the quiz.")
        questions.append(
            {
                "question": question,
                "choices": choices,
                "correct_answer": correct_answer,
                "explanation": _required_text(raw_question, "explanation", "the quiz"),
            }
        )
    return {"questions": questions}


def generate_quiz(subject, goal, topic, knowledge_level="Beginner"):
    if not is_gemini_quiz_enabled():
        return _local_quiz(subject, goal, topic, knowledge_level)

    prompt = """
Create exactly five distinct multiple-choice practice questions as JSON only.
The only allowed subject is: {subject}
Learner's current level: {knowledge_level}
Every question, answer, and explanation must test knowledge of this exact subject.
Do not include questions from another subject, even if they are commonly taught
alongside it. Do not use the study plan, learning goal, or topic text as a source.
For programming-language subjects, questions may test that language's code output,
syntax, keywords, or behavior. Do not assume the subject is a programming language.

Return exactly this shape:
{{
  "questions": [
    {{
      "question": "first clear question about the subject",
      "choices": ["option 1", "option 2", "option 3", "option 4"],
      "correct_answer": 0,
      "explanation": "brief explanation of the correct answer"
    }},
    {{
      "question": "second distinct question",
      "choices": ["option 1", "option 2", "option 3", "option 4"],
      "correct_answer": 0,
      "explanation": "brief explanation"
    }},
    {{
      "question": "third distinct question",
      "choices": ["option 1", "option 2", "option 3", "option 4"],
      "correct_answer": 0,
      "explanation": "brief explanation"
    }},
    {{
      "question": "fourth distinct question",
      "choices": ["option 1", "option 2", "option 3", "option 4"],
      "correct_answer": 0,
      "explanation": "brief explanation"
    }},
    {{
      "question": "fifth distinct question",
      "choices": ["option 1", "option 2", "option 3", "option 4"],
      "correct_answer": 0,
      "explanation": "brief explanation"
    }}
  ]
}}

Return exactly five distinct questions, each with exactly four distinct choices
and one correct answer. correct_answer is the zero-based index of the correct
choice. Include a short explanation for each. Test actual knowledge of the
subject, not the learner's goal or any study-plan topic, objectives, or key
points. Adapt question difficulty, terminology, and explanation depth to the
learner's current level. For a programming language, include code-output,
syntax, keyword, and language-behavior questions using valid code in that
language. Do not ask about general study habits.
""".format(
        subject=subject,
        knowledge_level=knowledge_level,
    )
    return _validate_quiz(_generate_json(prompt))
