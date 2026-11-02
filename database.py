import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path


DATABASE_PATH = Path(os.getenv("DATABASE_PATH", "learning_coach.db"))


def _connect():
    if DATABASE_PATH.parent != Path("."):
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with closing(_connect()) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS study_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal TEXT NOT NULL,
                subject TEXT NOT NULL,
                knowledge_level TEXT NOT NULL,
                duration_weeks INTEGER NOT NULL,
                daily_minutes INTEGER NOT NULL,
                plan_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                choices_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL,
                selected_index INTEGER NOT NULL,
                explanation TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id INTEGER NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                correct_count INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                choices_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL,
                selected_index INTEGER NOT NULL,
                explanation TEXT NOT NULL
            )
            """
        )


def save_plan(goal, subject, knowledge_level, duration_weeks, daily_minutes, plan):
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO study_plans
                (goal, subject, knowledge_level, duration_weeks, daily_minutes, plan_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                goal,
                subject,
                knowledge_level,
                duration_weeks,
                daily_minutes,
                json.dumps(plan),
            ),
        )
        return cursor.lastrowid


def get_plans():
    with closing(_connect()) as connection, connection:
        rows = connection.execute(
            """
            SELECT id, goal, subject, knowledge_level, duration_weeks, daily_minutes, created_at
            FROM study_plans
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_plan(plan_id):
    with closing(_connect()) as connection, connection:
        row = connection.execute(
            "SELECT * FROM study_plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
    if row is None:
        return None
    plan = dict(row)
    plan["plan"] = json.loads(plan.pop("plan_json"))
    return plan


def save_attempt(plan_id, topic, question, choices, correct_index, selected_index, explanation):
    is_correct = selected_index == correct_index
    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO quiz_attempts
                (plan_id, topic, question, choices_json, correct_index, selected_index,
                 explanation, is_correct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                topic,
                question,
                json.dumps(choices),
                correct_index,
                selected_index,
                explanation,
                int(is_correct),
            ),
        )
        attempt_id = cursor.lastrowid
    return {
        "id": attempt_id,
        "plan_id": plan_id,
        "topic": topic,
        "is_correct": is_correct,
        "correct_answer": choices[correct_index],
        "selected_answer": choices[selected_index],
        "explanation": explanation,
    }


def get_attempts(plan_id=None):
    query = """
        SELECT id, plan_id, topic, question, choices_json, correct_index, selected_index,
               explanation, is_correct, created_at
        FROM quiz_attempts
    """
    parameters = ()
    if plan_id is not None:
        query += " WHERE plan_id = ?"
        parameters = (plan_id,)
    query += " ORDER BY id DESC"

    with closing(_connect()) as connection, connection:
        rows = connection.execute(query, parameters).fetchall()
    attempts = []
    for row in rows:
        attempt = dict(row)
        choices = json.loads(attempt.pop("choices_json"))
        attempt["is_correct"] = bool(attempt["is_correct"])
        attempt["selected_answer"] = choices[attempt.pop("selected_index")]
        attempt["correct_answer"] = choices[attempt.pop("correct_index")]
        attempts.append(attempt)
    return attempts


def get_topic_stats(plan_id):
    with closing(_connect()) as connection, connection:
        rows = connection.execute(
            """
            SELECT topic, is_correct
            FROM quiz_attempts
            WHERE plan_id = ?
            UNION ALL
            SELECT s.topic, (r.correct_index = r.selected_index) AS is_correct
            FROM quiz_sessions AS s
            JOIN quiz_responses AS r ON r.session_id = s.id
            WHERE s.plan_id = ?
            """,
            (plan_id, plan_id),
        ).fetchall()
    stats = {}
    for row in rows:
        stat = stats.setdefault(
            row["topic"],
            {"topic": row["topic"], "attempt_count": 0, "correct_count": 0},
        )
        stat["attempt_count"] += 1
        stat["correct_count"] += int(row["is_correct"])
    return [
        dict(stat, accuracy=stat["correct_count"] / stat["attempt_count"])
        for stat in sorted(stats.values(), key=lambda item: item["topic"])
    ]


def save_quiz_session(plan_id, topic, questions, selected_indices):
    if len(questions) != 5 or len(selected_indices) != 5:
        raise ValueError("A quiz session must contain exactly five answered questions.")

    correct_count = 0
    for question, selected_index in zip(questions, selected_indices):
        if (
            not isinstance(selected_index, int)
            or isinstance(selected_index, bool)
            or not 0 <= selected_index < len(question["choices"])
        ):
            raise ValueError("A selected answer is outside the available choices.")
        if selected_index == question["correct_answer"]:
            correct_count += 1

    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO quiz_sessions (plan_id, topic, correct_count, total_questions)
            VALUES (?, ?, ?, ?)
            """,
            (plan_id, topic, correct_count, len(questions)),
        )
        session_id = cursor.lastrowid
        for question, selected_index in zip(questions, selected_indices):
            connection.execute(
                """
                INSERT INTO quiz_responses
                    (session_id, question, choices_json, correct_index, selected_index, explanation)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    question["question"],
                    json.dumps(question["choices"]),
                    question["correct_answer"],
                    selected_index,
                    question["explanation"],
                ),
            )

    return {
        "id": session_id,
        "plan_id": plan_id,
        "topic": topic,
        "correct_count": correct_count,
        "total_questions": len(questions),
        "score": correct_count / len(questions),
    }


def get_quiz_sessions(plan_id=None):
    query = """
        SELECT id, plan_id, topic, correct_count, total_questions, created_at
        FROM quiz_sessions
    """
    parameters = ()
    if plan_id is not None:
        query += " WHERE plan_id = ?"
        parameters = (plan_id,)
    query += " ORDER BY created_at, id"

    with closing(_connect()) as connection, connection:
        sessions = connection.execute(query, parameters).fetchall()
        results = []
        for session in sessions:
            answer_rows = connection.execute(
                """
                SELECT question, choices_json, correct_index, selected_index, explanation
                FROM quiz_responses
                WHERE session_id = ?
                ORDER BY id
                """,
                (session["id"],),
            ).fetchall()
            answers = []
            for answer in answer_rows:
                choices = json.loads(answer["choices_json"])
                correct_index = answer["correct_index"]
                selected_index = answer["selected_index"]
                answers.append(
                    {
                        "question": answer["question"],
                        "selected_answer": choices[selected_index],
                        "correct_answer": choices[correct_index],
                        "is_correct": selected_index == correct_index,
                        "explanation": answer["explanation"],
                    }
                )
            result = dict(session)
            result["score"] = result["correct_count"] / result["total_questions"]
            result["answers"] = answers
            results.append(result)

        legacy_query = """
            SELECT id, plan_id, topic, question, choices_json, correct_index, selected_index,
                   explanation, is_correct, created_at
            FROM quiz_attempts
        """
        legacy_parameters = ()
        if plan_id is not None:
            legacy_query += " WHERE plan_id = ?"
            legacy_parameters = (plan_id,)
        legacy_query += " ORDER BY created_at, id"
        legacy_rows = connection.execute(legacy_query, legacy_parameters).fetchall()

    for row in legacy_rows:
        choices = json.loads(row["choices_json"])
        correct_index = row["correct_index"]
        selected_index = row["selected_index"]
        results.append(
            {
                "id": "legacy-{}".format(row["id"]),
                "plan_id": row["plan_id"],
                "topic": row["topic"],
                "correct_count": int(row["is_correct"]),
                "total_questions": 1,
                "score": float(row["is_correct"]),
                "created_at": row["created_at"],
                "answers": [
                    {
                        "question": row["question"],
                        "selected_answer": choices[selected_index],
                        "correct_answer": choices[correct_index],
                        "is_correct": bool(row["is_correct"]),
                        "explanation": row["explanation"],
                    }
                ],
            }
        )

    results.sort(key=lambda result: (result["created_at"], str(result["id"])))
    for attempt_number, result in enumerate(results, start=1):
        result["attempt_number"] = attempt_number
    return list(reversed(results))
