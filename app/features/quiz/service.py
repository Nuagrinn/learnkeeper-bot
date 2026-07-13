from __future__ import annotations

import json
import logging
import hashlib
import uuid
from datetime import datetime

from app.core.db import Database
from app.core.repo import RepoService, RepoTopic, TopicMaterial, TopicMaterials, slugify
from app.features.quiz.generator import QuizGenerator
from app.features.quiz.models import (
    AnswerQuizResult,
    GeneratedQuestion,
    QuizAnswer,
    QuizQuestion,
    QuizSession,
    StartQuizResult,
    quiz_answer_from_row,
    quiz_question_from_row,
    quiz_session_from_row,
)
from app.features.review_tasks.service import ACTIVE, ReviewTaskService


log = logging.getLogger(__name__)
IN_PROGRESS = "in_progress"
FINISHED = "finished"
DEFAULT_QUESTION_COUNT = 5
SESSION_REVIEW = "review"
SESSION_INSTANT = "instant"


class QuestionClosedError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _id() -> str:
    return uuid.uuid4().hex[:12]


class QuizService:
    def __init__(
        self,
        db: Database,
        repo: RepoService,
        review_tasks: ReviewTaskService,
        generator: QuizGenerator,
        *,
        pull_before_quiz: bool = False,
        git_remote: str = "origin",
        git_branch: str = "",
        pull_timeout_seconds: int = 120,
    ):
        self.db = db
        self.repo = repo
        self.review_tasks = review_tasks
        self.generator = generator
        self.pull_before_quiz = pull_before_quiz
        self.git_remote = git_remote
        self.git_branch = git_branch
        self.pull_timeout_seconds = pull_timeout_seconds

    def _sync_repo(self) -> None:
        """Best-effort refresh of lk-prep right before reading materials."""
        if not self.pull_before_quiz:
            return
        try:
            result = self.repo.pull_latest(
                remote=self.git_remote,
                branch=self.git_branch,
                timeout_seconds=self.pull_timeout_seconds,
            )
            log.info("Repo pull before quiz status=%s", result.status)
        except Exception:
            log.exception("Repo pull before quiz failed unexpectedly")

    def start_session(
        self,
        task_id: str,
        *,
        question_count: int = DEFAULT_QUESTION_COUNT,
        now: datetime | None = None,
    ) -> StartQuizResult:
        now = (now or _now()).replace(microsecond=0)
        task = self.review_tasks.get_task(task_id)
        if task.status != ACTIVE:
            raise ValueError(f"Review task {task_id} is not active")

        existing = self._active_session_for_task(task_id)
        if existing:
            log.info(
                "Reusing active quiz session task_id=%s session_id=%s question_no=%s",
                task_id,
                existing.id,
                existing.current_question_no,
            )
            question = self.current_question(existing.id)
            return StartQuizResult(session=existing, question=question, created=False)

        self._sync_repo()
        count = max(1, min(40, int(question_count)))
        topic = self.repo.get_topic(task.topic_id) or RepoTopic(
            id=task.topic_id,
            title=task.topic_title,
        )
        materials = self.repo.get_topic_materials(topic)
        return self._create_generated_session(
            topic=topic,
            materials=materials,
            question_count=count,
            now=now,
            session_type=SESSION_REVIEW,
            task_id=task.id,
        )

    def start_instant_topic_session(
        self,
        topic_id: str,
        *,
        question_count: int = DEFAULT_QUESTION_COUNT,
        now: datetime | None = None,
    ) -> StartQuizResult:
        now = (now or _now()).replace(microsecond=0)
        self._sync_repo()
        topic = self.repo.get_topic(topic_id)
        if not topic:
            raise ValueError(f"Topic not found: {topic_id}")
        materials = self.repo.get_topic_materials(topic)
        if not materials.files:
            raise ValueError(f"Topic {topic.title} has no readable materials")
        return self._create_generated_session(
            topic=topic,
            materials=materials,
            question_count=max(1, min(40, int(question_count))),
            now=now,
            session_type=SESSION_INSTANT,
            task_id=None,
        )

    def start_instant_block_session(
        self,
        section: str,
        *,
        question_count: int = DEFAULT_QUESTION_COUNT,
        now: datetime | None = None,
    ) -> StartQuizResult:
        now = (now or _now()).replace(microsecond=0)
        clean_section = section.strip()
        if not clean_section:
            raise ValueError("Section must not be empty")

        self._sync_repo()
        topics = [
            topic
            for topic in self.repo.list_topics()
            if topic.section == clean_section and topic.status == "ready"
        ]
        files: list[TopicMaterial] = []
        paths: list[str] = []
        seen_paths: set[str] = set()
        for topic in topics:
            materials = self.repo.get_topic_materials(topic)
            for file in materials.files:
                if file.source_path in seen_paths:
                    continue
                seen_paths.add(file.source_path)
                paths.append(file.source_path)
                files.append(file)
        if not files:
            raise ValueError(f"Section {clean_section} has no readable materials")

        topic = RepoTopic(
            id=f"block-{slugify(clean_section)}",
            title=f"Блок: {clean_section}",
            status="ready",
            section=clean_section,
            source_paths=paths,
            material_fingerprint=self.repo.material_fingerprint(paths),
        )
        materials = TopicMaterials(
            topic=topic,
            files=files,
            fingerprint=topic.material_fingerprint,
        )
        return self._create_generated_session(
            topic=topic,
            materials=materials,
            question_count=max(1, min(40, int(question_count))),
            now=now,
            session_type=SESSION_INSTANT,
            task_id=None,
        )

    def answer_current(
        self,
        session_id: str,
        question_id: str,
        selected_index: int,
        *,
        now: datetime | None = None,
    ) -> AnswerQuizResult:
        now = (now or _now()).replace(microsecond=0)
        if selected_index < 0 or selected_index > 3:
            raise ValueError("Selected index must be between 0 and 3")

        session = self.get_session(session_id)
        if session.status != IN_PROGRESS:
            raise QuestionClosedError("Quiz session is not in progress")

        question = self.current_question(session.id)
        if question.id != question_id:
            raise QuestionClosedError("This question is already closed")

        if self._answer_for_question(session.id, question.id):
            raise QuestionClosedError("This question is already answered")

        answer = QuizAnswer(
            id=_id(),
            session_id=session.id,
            question_id=question.id,
            selected_index=selected_index,
            is_correct=selected_index == question.correct_index,
            answered_at=now,
        )
        self._insert_answer(answer)

        if question.question_no >= session.question_count:
            finished = self._finish_session(session.id, now=now)
            task = None
            if finished.session_type == SESSION_REVIEW and finished.task_id:
                task = self.review_tasks.complete_task(
                    finished.task_id,
                    finished.score_percent or 0,
                    now=now,
                )
            return AnswerQuizResult(
                session=finished,
                question=question,
                answer=answer,
                next_question=None,
                finished_task=task,
            )

        self._advance_session(session.id, question.question_no + 1)
        updated = self.get_session(session.id)
        return AnswerQuizResult(
            session=updated,
            question=question,
            answer=answer,
            next_question=self.current_question(session.id),
            finished_task=None,
        )

    def get_session(self, session_id: str) -> QuizSession:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM quiz_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Quiz session not found: {session_id}")
        return quiz_session_from_row(row)

    def current_question(self, session_id: str) -> QuizQuestion:
        session = self.get_session(session_id)
        question = self._question_by_no(session.id, session.current_question_no)
        if question is None:
            raise ValueError(f"Question not found for session {session_id}")
        return question

    def questions(self, session_id: str) -> list[QuizQuestion]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM questions
                WHERE session_id = ?
                ORDER BY question_no
                """,
                (session_id,),
            ).fetchall()
        return [quiz_question_from_row(row) for row in rows]

    def answers(self, session_id: str) -> list[QuizAnswer]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT * FROM answers
                WHERE session_id = ?
                ORDER BY answered_at
                """,
                (session_id,),
            ).fetchall()
        return [quiz_answer_from_row(row) for row in rows]

    def _active_session_for_task(self, task_id: str) -> QuizSession | None:
        with self.db.session() as conn:
            row = conn.execute(
                """
                SELECT * FROM quiz_sessions
                WHERE task_id = ? AND status = ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (task_id, IN_PROGRESS),
            ).fetchone()
        return quiz_session_from_row(row) if row else None

    def _create_generated_session(
        self,
        *,
        topic: RepoTopic,
        materials: TopicMaterials,
        question_count: int,
        now: datetime,
        session_type: str,
        task_id: str | None,
    ) -> StartQuizResult:
        self._upsert_topic(topic, now=now)
        log.info(
            "Generating quiz session type=%s task_id=%s topic_id=%s question_count=%s source_files=%s fingerprint=%s",
            session_type,
            task_id or "-",
            topic.id,
            question_count,
            len(materials.files),
            materials.fingerprint[:12],
        )
        generated = self._validate_generated(
            self.generator.generate(
                topic=topic,
                materials=materials,
                question_count=question_count,
            )
        )
        session = QuizSession(
            id=_id(),
            task_id=task_id,
            topic_id=topic.id,
            topic_title=topic.title,
            session_type=session_type,
            status=IN_PROGRESS,
            question_count=len(generated),
            current_question_no=1,
            started_at=now,
            material_fingerprint=materials.fingerprint,
            material_snapshot=_material_snapshot(materials),
            generator_provider=getattr(self.generator, "provider", "unknown"),
            generator_model=getattr(self.generator, "model", ""),
            prompt_version=getattr(self.generator, "prompt_version", ""),
            generated_at=now,
        )
        self._insert_session(session, generated)
        log.info(
            "Created quiz session type=%s task_id=%s session_id=%s questions=%s provider=%s prompt_version=%s",
            session.session_type,
            session.task_id or "-",
            session.id,
            session.question_count,
            session.generator_provider,
            session.prompt_version,
        )
        return StartQuizResult(
            session=session,
            question=self.current_question(session.id),
            created=True,
        )

    def _upsert_topic(self, topic: RepoTopic, *, now: datetime) -> None:
        stamp = now.isoformat(timespec="seconds")
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO topics (
                    id, title, status, tags_json, source_paths_json,
                    last_seen_commit, section, order_index, material_fingerprint,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    status = excluded.status,
                    tags_json = excluded.tags_json,
                    source_paths_json = excluded.source_paths_json,
                    section = excluded.section,
                    order_index = excluded.order_index,
                    material_fingerprint = excluded.material_fingerprint,
                    updated_at = excluded.updated_at
                """,
                (
                    topic.id,
                    topic.title,
                    topic.status,
                    json.dumps(topic.tags, ensure_ascii=False),
                    json.dumps(topic.source_paths, ensure_ascii=False),
                    None,
                    topic.section,
                    topic.order_index,
                    topic.material_fingerprint,
                    stamp,
                    stamp,
                ),
            )

    def _insert_session(
        self,
        session: QuizSession,
        questions: list[GeneratedQuestion],
    ) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO quiz_sessions (
                    id, task_id, topic_id, topic_title, session_type, status, question_count,
                    current_question_no, started_at, finished_at,
                    material_fingerprint, material_snapshot_json,
                    generator_provider, generator_model, prompt_version, generated_at,
                    score_percent, correct_count, total_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.task_id,
                    session.topic_id,
                    session.topic_title,
                    session.session_type,
                    session.status,
                    session.question_count,
                    session.current_question_no,
                    session.started_at.isoformat(timespec="seconds"),
                    None,
                    session.material_fingerprint,
                    json.dumps(session.material_snapshot, ensure_ascii=False),
                    session.generator_provider,
                    session.generator_model,
                    session.prompt_version,
                    session.generated_at.isoformat(timespec="seconds")
                    if session.generated_at
                    else None,
                    None,
                    None,
                    None,
                ),
            )
            for no, question in enumerate(questions, start=1):
                conn.execute(
                    """
                    INSERT INTO questions (
                        id, session_id, question_no, text, options_json,
                        correct_index, explanation, source_refs_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _id(),
                        session.id,
                        no,
                        question.text,
                        json.dumps(question.options, ensure_ascii=False),
                        question.correct_index,
                        question.explanation,
                        json.dumps(question.source_refs, ensure_ascii=False),
                    ),
                )

    def _insert_answer(self, answer: QuizAnswer) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO answers (
                    id, session_id, question_id, selected_index, is_correct, answered_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    answer.id,
                    answer.session_id,
                    answer.question_id,
                    answer.selected_index,
                    1 if answer.is_correct else 0,
                    answer.answered_at.isoformat(timespec="seconds"),
                ),
            )

    def _advance_session(self, session_id: str, next_question_no: int) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE quiz_sessions
                SET current_question_no = ?
                WHERE id = ?
                """,
                (next_question_no, session_id),
            )

    def _finish_session(self, session_id: str, *, now: datetime) -> QuizSession:
        questions = self.questions(session_id)
        answers = self.answers(session_id)
        correct = sum(1 for answer in answers if answer.is_correct)
        total = len(questions)
        score = round((correct / total) * 100, 2) if total else 0.0
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE quiz_sessions
                SET status = ?,
                    finished_at = ?,
                    score_percent = ?,
                    correct_count = ?,
                    total_count = ?
                WHERE id = ?
                """,
                (
                    FINISHED,
                    now.isoformat(timespec="seconds"),
                    score,
                    correct,
                    total,
                    session_id,
                ),
            )
        return self.get_session(session_id)

    def _answer_for_question(self, session_id: str, question_id: str) -> QuizAnswer | None:
        with self.db.session() as conn:
            row = conn.execute(
                """
                SELECT * FROM answers
                WHERE session_id = ? AND question_id = ?
                """,
                (session_id, question_id),
            ).fetchone()
        return quiz_answer_from_row(row) if row else None

    def _question_by_no(self, session_id: str, question_no: int) -> QuizQuestion | None:
        with self.db.session() as conn:
            row = conn.execute(
                """
                SELECT * FROM questions
                WHERE session_id = ? AND question_no = ?
                """,
                (session_id, question_no),
            ).fetchone()
        return quiz_question_from_row(row) if row else None

    def _validate_generated(
        self,
        questions: list[GeneratedQuestion],
    ) -> list[GeneratedQuestion]:
        if not questions:
            raise ValueError("Quiz generator returned no questions")
        for question in questions:
            if not question.text.strip():
                raise ValueError("Question text must not be empty")
            if len(question.options) != 4:
                raise ValueError("Question must have exactly 4 options")
            if question.correct_index < 0 or question.correct_index > 3:
                raise ValueError("Question correct_index must be between 0 and 3")
            if any(not option.strip() for option in question.options):
                raise ValueError("Question options must not be empty")
        return questions


def _material_snapshot(materials: TopicMaterials) -> dict[str, object]:
    return {
        "topic_id": materials.topic.id,
        "topic_title": materials.topic.title,
        "source_paths": [file.source_path for file in materials.files],
        "fingerprint": materials.fingerprint,
        "metadata": [_material_metadata_snapshot(file) for file in materials.files],
    }


def _material_metadata_snapshot(file: TopicMaterial) -> dict[str, object]:
    metadata = file.metadata
    return {
        "source_path": file.source_path,
        "source_role": metadata.source_role,
        "source_refs": metadata.source_refs,
        "prompt_helper_hash": _prompt_helper_hash(metadata.prompt_helper),
        "challenge_helper_hash": _prompt_helper_hash(metadata.challenge_helper),
    }


def _prompt_helper_hash(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
