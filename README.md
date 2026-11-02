# AI Personalized Learning Coach

A Streamlit learning app that turns a learner's goal, subject, current knowledge,
study schedule, and quiz results into a personalized study workflow.

## What it does

- Builds a week-by-week study plan from a learning goal, subject, skill level,
  target duration, and daily study time. Each topic includes a validated
  estimated duration, and weekly estimates cannot exceed the available study
  time.
- Creates five-question subject-knowledge quizzes with four choices per
  question. Learners answer one question at a time and see feedback before
  moving to the next question.
- Local quizzes are available for Python and Physics. Python questions test
  code output, syntax, and keyword behavior; Physics questions test physics
  concepts and calculations.
- Quiz content is limited to the selected subject. Local quiz generation
  currently supports Python and Physics; for other subjects, configure Gemini
  quiz generation with `GEMINI_GENERATE_QUIZZES=true` rather than receiving
  unrelated fallback questions.
- Tracks quiz-attempt scores and accuracy by topic to highlight areas to revisit.
- Shows completed quiz count, questions answered, each quiz score, and overall
  performance on the dashboard.
- The dashboard displays the selected saved study plan, recommends a specific
  topic and activity based on quiz performance, and shows recent quiz history.
- Stores study plans and learning history in SQLite.
- Shows plan and progress history in a Streamlit dashboard.
- Uses Gemini for subject-specific study plans when configured. Quizzes use local
  generation by default for instant responses; optionally enable Gemini quizzes,
  which are prompted to test only the selected subject, not study-plan text or
  other subjects, and adapt question difficulty and explanation depth to the
  learner's level. Local quiz explanations also use more technical detail for
  advanced learners.
- Calculates quiz scores in Python from the validated correct-answer indices;
  the model does not calculate scores. Dashboard results are progress indicators,
  not claims of mastery from a small quiz.
- Shows a retry action when quiz generation fails. Each completed quiz is stored
  as a separate database session and remains in dashboard history after restart.
- Recommends moving to the next planned topic after strong results, or trying
  harder practice after strong results across all planned topics.
- If Gemini's request quota is exhausted or it cannot be reached while creating
  a plan, the app saves a local template plan and clearly labels it so learning
  can continue.

## Run locally

The project has been tested with Python 3.9 or newer.

1. Open a terminal in the project folder.
2. Create and activate a virtual environment if you do not already have one:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. (Optional) Configure Gemini. Copy `.env.example` to `.env` and add your API
   key. Keep `.env` private and do not commit it.
5. Start the app:

   ```powershell
   streamlit run app.py
   ```

Without a Gemini key, the local demo mode still lets you create plans, take
template quizzes, and explore the dashboard. For AI-generated subject-specific
content, set `GEMINI_API_KEY` in `.env`. The model defaults to
`gemini-3.8-flash`; override it with `GEMINI_MODEL` if needed.
When `GEMINI_API_KEY` is configured, Gemini quizzes are enabled by default for
all subjects. To use the local Python and Physics quizzes instead, set
`GEMINI_GENERATE_QUIZZES=false` in `.env`. Without a Gemini key, local quizzes
are used for Python and Physics; other subjects show a clear configuration
error. Gemini-generated quizzes may take longer and can be affected by service
availability.

## Data and configuration

- The default SQLite database is `learning_coach.db` in the project folder.
- Set `DATABASE_PATH` to use a different database file.
- Each completed quiz stores its questions, selected and correct answers,
  score, explanation, topic, and timestamp.
- The app does not require an account; data saved in the SQLite database is
  local to the machine.

## Project files

- `app.py` — Streamlit forms, study plan display, quiz flow, and dashboard.
- `ai_service.py` — Gemini prompts, response validation, and local demo content.
- `database.py` — SQLite schema and persistence helpers.
- `learning_plan.py` — plan-generation and persistence workflow.
- `quiz_manager.py` — quiz-generation and answer-submission workflow.
- `sample_data/example_learning_plan.json` — the latest generated study plan,
  overwritten each time a new plan is created. Its structure matches the plan
  validated by `ai_service.py`.