from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.db import Database
from app.core.repo import RepoService, RepoTopic, TopicMaterial, TopicMaterials
from app.features.open_questions.agent import (
    GeneratedOpenQuestion,
    OpenQuestionAgent,
    OpenQuestionCheckInput,
    OpenQuestionGenerationInput,
)
from app.features.open_questions.models import (
    OpenQuestion,
    OpenQuestionAttempt,
    open_question_attempt_from_row,
    open_question_from_row,
)
from app.features.quiz.generator import CODE_FILE_EXTENSIONS, MATERIAL_CHAR_LIMIT
from app.features.quiz.models import QuizAnswer, QuizQuestion, QuizSession


log = logging.getLogger(__name__)

ACTIVE = "active"
ANSWERED = "answered"
DELETED = "deleted"

ORIGIN_INSTANT = "instant"
ORIGIN_POST_QUIZ = "post_quiz"


class OpenQuestionService:
    def __init__(
        self,
        db: Database,
        repo: RepoService,
        agent: OpenQuestionAgent,
        *,
        pull_before_question: bool = False,
        git_remote: str = "origin",
        git_branch: str = "",
        pull_timeout_seconds: int = 120,
    ):
        self.db = db
        self.repo = repo
        self.agent = agent
        self.pull_before_question = pull_before_question
        self.git_remote = git_remote
        self.git_branch = git_branch
        self.pull_timeout_seconds = pull_timeout_seconds

    def _sync_repo(self) -> None:
        if not self.pull_before_question:
            return
        try:
            result = self.repo.pull_latest(
                remote=self.git_remote,
                branch=self.git_branch,
                timeout_seconds=self.pull_timeout_seconds,
            )
            log.info("Repo pull before open question status=%s", result.status)
        except Exception:
            log.exception("Repo pull before open question failed unexpectedly")

    def generate_for_topic(
        self,
        topic_id: str,
        *,
        origin: str = ORIGIN_INSTANT,
        now: datetime | None = None,
    ) -> OpenQuestion:
        self._sync_repo()
        topic = self.repo.get_topic(topic_id)
        if not topic:
            raise ValueError(f"Topic not found: {topic_id}")
        materials = self.repo.get_topic_materials(topic)
        if not materials.files:
            raise ValueError(f"Topic {topic.title} has no readable materials")
        generated = self.agent.generate(
            OpenQuestionGenerationInput(
                topic_id=topic.id,
                topic_title=topic.title,
                section=topic.section,
                origin=origin,
                material_context=_material_context(materials),
            )
        )
        return self._create_question(
            topic=topic,
            materials=materials,
            generated=generated,
            origin=origin,
            quiz_session_id="",
            now=now,
        )

    def generate_for_quiz(
        self,
        *,
        session: QuizSession,
        questions: list[QuizQuestion],
        answers: list[QuizAnswer],
        now: datetime | None = None,
    ) -> OpenQuestion:
        self._sync_repo()
        topic = self.repo.get_topic(session.topic_id) or RepoTopic(
            id=session.topic_id,
            title=session.topic_title or session.topic_id,
            status="ready",
            section="",
        )
        materials = self.repo.get_topic_materials(topic)
        if not materials.files:
            raise ValueError(f"Topic {topic.title} has no readable materials")
        generated = self.agent.generate(
            OpenQuestionGenerationInput(
                topic_id=topic.id,
                topic_title=topic.title,
                section=topic.section,
                origin=ORIGIN_POST_QUIZ,
                material_context=_material_context(materials),
                quiz_context=_quiz_context(session, questions, answers),
            )
        )
        return self._create_question(
            topic=topic,
            materials=materials,
            generated=generated,
            origin=ORIGIN_POST_QUIZ,
            quiz_session_id=session.id,
            now=now,
        )

    def check_answer(
        self,
        question_id: str,
        answer_text: str,
        *,
        answer_source: str = "text",
        now: datetime | None = None,
    ) -> tuple[OpenQuestion, OpenQuestionAttempt]:
        question = self.get_question(question_id)
        if not question:
            raise ValueError(f"Open question not found: {question_id}")
        if question.status != ACTIVE:
            raise ValueError("Open question is already answered or closed")
        clean_answer = answer_text.strip()
        if not clean_answer:
            raise ValueError("Answer must not be empty")

        self._sync_repo()
        topic = self.repo.get_topic(question.topic_id) or RepoTopic(
            id=question.topic_id,
            title=question.topic_title,
            status="ready",
            section=question.section,
        )
        materials = self.repo.get_topic_materials(topic)
        result = self.agent.check(
            OpenQuestionCheckInput(
                open_question_id=question.id,
                topic_id=question.topic_id,
                topic_title=question.topic_title,
                section=question.section,
                question_kind=question.question_kind,
                question_text=question.question_text,
                answer_format_hint=question.answer_format_hint,
                expected_points=question.expected_points,
                rubric=question.rubric,
                source_refs=question.source_refs,
                answer_text=clean_answer,
                answer_source=answer_source,
                material_context=_material_context(materials),
            )
        )
        attempt = OpenQuestionAttempt(
            id=_id(),
            open_question_id=question.id,
            answer_text=clean_answer,
            answer_source=answer_source,
            score_percent=result.score_percent,
            layer_reached=result.layer_reached,
            summary=result.summary,
            strong_points=result.strong_points,
            missing_points=result.missing_points,
            false_models=result.false_models,
            better_answer=result.better_answer,
            next_drill=result.next_drill,
            should_create_mistake_work=result.should_create_mistake_work,
            checker_provider=result.provider,
            checker_model=result.model,
            check_prompt_version=result.prompt_version,
            raw_report=result.raw_payload or {},
            created_at=(now or _now()).replace(microsecond=0),
        )
        self._insert_attempt(attempt)
        self._mark_answered(question.id, now=attempt.created_at)
        updated = self.get_question(question.id) or question
        return updated, attempt

    def get_question(self, question_id: str) -> OpenQuestion | None:
        with self.db.session() as conn:
            row = conn.execute(
                "SELECT * FROM open_questions WHERE id = ?",
                (question_id.strip(),),
            ).fetchone()
        return open_question_from_row(row) if row else None

    def latest_attempt(self, question_id: str) -> OpenQuestionAttempt | None:
        with self.db.session() as conn:
            row = conn.execute(
                """
                SELECT * FROM open_question_attempts
                WHERE open_question_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (question_id.strip(),),
            ).fetchone()
        return open_question_attempt_from_row(row) if row else None

    def list_active(self, *, limit: int = 20) -> list[OpenQuestion]:
        return self._list_by_status(ACTIVE, limit=limit)

    def list_answered(self, *, limit: int = 20) -> list[OpenQuestion]:
        return self._list_by_status(ANSWERED, limit=limit)

    def delete_question(self, question_id: str) -> OpenQuestion:
        question = self.get_question(question_id)
        if not question:
            raise ValueError("Open question not found")
        now = _now()
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE open_questions
                SET status = ?, updated_at = ?, deleted_at = ?
                WHERE id = ?
                """,
                (DELETED, now.isoformat(), now.isoformat(), question.id),
            )
        updated = self.get_question(question.id)
        if not updated:
            raise ValueError("Open question not found after delete")
        return updated

    def _list_by_status(self, status: str, *, limit: int) -> list[OpenQuestion]:
        with self.db.session() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM open_questions
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, max(1, min(100, int(limit)))),
            ).fetchall()
        return [open_question_from_row(row) for row in rows]

    def _create_question(
        self,
        *,
        topic: RepoTopic,
        materials: TopicMaterials,
        generated: GeneratedOpenQuestion,
        origin: str,
        quiz_session_id: str,
        now: datetime | None,
    ) -> OpenQuestion:
        created = (now or _now()).replace(microsecond=0)
        question = OpenQuestion(
            id=_id(),
            topic_id=topic.id,
            topic_title=topic.title,
            section=topic.section,
            quiz_session_id=quiz_session_id,
            origin=origin,
            status=ACTIVE,
            question_kind=generated.question_kind,
            question_text=generated.question,
            answer_format_hint=generated.answer_format_hint,
            expected_points=generated.expected_points,
            rubric=generated.rubric,
            source_refs=generated.source_refs,
            material_fingerprint=materials.fingerprint,
            material_snapshot=_material_snapshot(materials),
            generator_provider=generated.provider,
            generator_model=generated.model,
            generate_prompt_version=generated.prompt_version,
            created_at=created,
            updated_at=created,
        )
        self._insert_question(question)
        log.info(
            "Open question created id=%s origin=%s topic_id=%s provider=%s",
            question.id,
            question.origin,
            question.topic_id,
            question.generator_provider,
        )
        return question

    def _insert_question(self, question: OpenQuestion) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO open_questions (
                    id, topic_id, topic_title, section, quiz_session_id, origin,
                    status, question_kind, question_text, answer_format_hint,
                    expected_points_json, rubric_json, source_refs_json,
                    material_fingerprint, material_snapshot_json,
                    generator_provider, generator_model, generate_prompt_version,
                    created_at, updated_at, answered_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    question.id,
                    question.topic_id,
                    question.topic_title,
                    question.section,
                    question.quiz_session_id,
                    question.origin,
                    question.status,
                    question.question_kind,
                    question.question_text,
                    question.answer_format_hint,
                    json.dumps(question.expected_points, ensure_ascii=False),
                    json.dumps(question.rubric, ensure_ascii=False),
                    json.dumps(question.source_refs, ensure_ascii=False),
                    question.material_fingerprint,
                    json.dumps(question.material_snapshot, ensure_ascii=False),
                    question.generator_provider,
                    question.generator_model,
                    question.generate_prompt_version,
                    question.created_at.isoformat(timespec="seconds"),
                    question.updated_at.isoformat(timespec="seconds"),
                    None,
                    None,
                ),
            )

    def _insert_attempt(self, attempt: OpenQuestionAttempt) -> None:
        with self.db.session() as conn:
            conn.execute(
                """
                INSERT INTO open_question_attempts (
                    id, open_question_id, answer_text, answer_source,
                    score_percent, layer_reached, summary,
                    strong_points_json, missing_points_json, false_models_json,
                    better_answer, next_drill, should_create_mistake_work,
                    checker_provider, checker_model, check_prompt_version,
                    raw_report_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.id,
                    attempt.open_question_id,
                    attempt.answer_text,
                    attempt.answer_source,
                    attempt.score_percent,
                    attempt.layer_reached,
                    attempt.summary,
                    json.dumps(attempt.strong_points, ensure_ascii=False),
                    json.dumps(attempt.missing_points, ensure_ascii=False),
                    json.dumps(attempt.false_models, ensure_ascii=False),
                    attempt.better_answer,
                    attempt.next_drill,
                    1 if attempt.should_create_mistake_work else 0,
                    attempt.checker_provider,
                    attempt.checker_model,
                    attempt.check_prompt_version,
                    json.dumps(attempt.raw_report, ensure_ascii=False),
                    attempt.created_at.isoformat(timespec="seconds"),
                ),
            )

    def _mark_answered(self, question_id: str, *, now: datetime) -> None:
        stamp = now.isoformat(timespec="seconds")
        with self.db.session() as conn:
            conn.execute(
                """
                UPDATE open_questions
                SET status = ?, updated_at = ?, answered_at = ?
                WHERE id = ?
                """,
                (ANSWERED, stamp, stamp, question_id),
            )


def _material_context(materials: TopicMaterials) -> list[dict[str, Any]]:
    files = [
        file
        for file in materials.files
        if Path(file.source_path).suffix.lower() not in CODE_FILE_EXTENSIONS
    ]
    if not files:
        files = materials.files
    remaining = MATERIAL_CHAR_LIMIT
    result: list[dict[str, Any]] = []
    for file in files:
        if remaining <= 0:
            break
        excerpt = file.content[:remaining]
        remaining -= len(excerpt)
        result.append(_material_context_entry(file, excerpt))
    return result


def _material_context_entry(material: TopicMaterial, excerpt: str) -> dict[str, Any]:
    metadata = material.metadata
    entry: dict[str, Any] = {
        "source_path": material.source_path,
        "excerpt": excerpt,
    }
    if metadata.source_role:
        entry["source_role"] = metadata.source_role
    if metadata.source_refs:
        entry["source_refs"] = metadata.source_refs
    if metadata.prompt_helper:
        entry["prompt_helper"] = metadata.prompt_helper
    if metadata.challenge_helper:
        entry["challenge_helper"] = metadata.challenge_helper
    return entry


def _quiz_context(
    session: QuizSession,
    questions: list[QuizQuestion],
    answers: list[QuizAnswer],
) -> dict[str, Any]:
    answer_by_question = {answer.question_id: answer for answer in answers}
    mistakes: list[dict[str, Any]] = []
    for question in questions:
        answer = answer_by_question.get(question.id)
        if not answer or answer.is_correct:
            continue
        mistakes.append(
            {
                "question_no": question.question_no,
                "question": question.text,
                "selected_index": answer.selected_index,
                "correct_index": question.correct_index,
                "explanation": question.explanation,
                "source_refs": question.source_refs,
            }
        )
    return {
        "quiz_session_id": session.id,
        "session_type": session.session_type,
        "score_percent": session.score_percent,
        "correct_count": session.correct_count,
        "total_count": session.total_count,
        "mistakes": mistakes[:10],
    }


def _material_snapshot(materials: TopicMaterials) -> dict[str, Any]:
    return {
        "topic_id": materials.topic.id,
        "topic_title": materials.topic.title,
        "source_paths": [file.source_path for file in materials.files],
        "fingerprint": materials.fingerprint,
        "metadata": [_material_metadata_snapshot(file) for file in materials.files],
    }


def _material_metadata_snapshot(file: TopicMaterial) -> dict[str, Any]:
    metadata = file.metadata
    return {
        "source_path": file.source_path,
        "source_role": metadata.source_role,
        "source_refs": metadata.source_refs,
        "prompt_helper_hash": _text_hash(metadata.prompt_helper),
        "challenge_helper_hash": _text_hash(metadata.challenge_helper),
    }


def _text_hash(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _id() -> str:
    return uuid.uuid4().hex[:12]
