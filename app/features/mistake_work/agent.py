from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from app.config import PROJECT_ROOT
from app.features.llm_usage.service import LlmUsageRecorder, NoopLlmUsageRecorder
from app.features.quiz.generator import PAID_API_ENV_VARS, _claude_cli_reported_usage


log = logging.getLogger(__name__)

PROMPT_VERSION = "learnkeeper-mistake-review-v2"
PRIORITIES = {"low", "normal", "high"}
MISTAKE_REVIEW_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "section",
        "priority",
        "summary",
        "diagnosis",
        "weak_concepts",
        "interview_review_suggestion",
        "questions_to_revisit",
    ],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "section": {"type": "string"},
        "priority": {"type": "string", "enum": ["low", "normal", "high"]},
        "summary": {"type": "string"},
        "diagnosis": {"type": "string"},
        "weak_concepts": {"type": "array", "items": {"type": "string"}},
        "interview_review_suggestion": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "target_section", "details"],
            "properties": {
                "title": {"type": "string"},
                "target_section": {"type": "string"},
                "details": {"type": "string"},
            },
        },
        "questions_to_revisit": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "question_no",
                    "missed_point",
                    "correct_idea",
                    "practice_prompt",
                ],
                "properties": {
                    "question_no": {"type": "integer"},
                    "missed_point": {"type": "string"},
                    "correct_idea": {"type": "string"},
                    "practice_prompt": {"type": "string"},
                },
            },
        },
    },
}


@dataclass(frozen=True)
class MistakeReviewInput:
    quiz_session_id: str
    topic_id: str
    topic_title: str
    section: str
    session_type: str
    score_percent: float
    correct_count: int
    total_count: int
    mistakes: list[dict[str, Any]]
    material_context: list[dict[str, str]]


@dataclass(frozen=True)
class MistakeReviewResult:
    title: str
    section: str
    priority: str
    summary: str
    diagnosis: str
    weak_concepts: list[str]
    interview_review_suggestion: dict[str, Any]
    questions_to_revisit: list[dict[str, Any]]
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION
    raw_payload: dict[str, Any] | None = None


class MistakeReviewAgentError(RuntimeError):
    pass


class MistakeReviewAgent(Protocol):
    provider: str
    model: str
    prompt_version: str

    def analyze(self, request: MistakeReviewInput) -> MistakeReviewResult:
        ...


class FakeMistakeReviewAgent:
    provider = "fake"
    model = "fake"
    prompt_version = "fake-mistake-review-v1"

    def analyze(self, request: MistakeReviewInput) -> MistakeReviewResult:
        first = request.mistakes[0] if request.mistakes else {}
        weak_concepts = _weak_concepts_from_mistakes(request.mistakes)
        title = f"Разбор ошибок: {request.topic_title}"
        diagnosis = (
            "Fake agent: отчет собран локально по неправильным ответам без обращения к LLM."
        )
        if first:
            diagnosis = (
                f"Первый проваленный вопрос: {first.get('question', '')}. "
                "Проверь объяснения к ошибкам и дополни материал вручную."
            )
        suggestion = {
            "title": title,
            "target_section": request.section,
            "details": "Добавить короткий блок с разбором ошибочных вопросов и практическими примерами.",
        }
        questions = [
            {
                "question_no": int(item.get("question_no") or 0),
                "missed_point": str(item.get("question") or "")[:240],
                "correct_idea": str(item.get("explanation") or "")[:400],
                "practice_prompt": "Сформулировать ответ своими словами и привести пример.",
            }
            for item in request.mistakes[:8]
        ]
        return MistakeReviewResult(
            title=title,
            section=request.section,
            priority="normal",
            summary=f"Ошибок: {len(request.mistakes)} из {request.total_count}.",
            diagnosis=diagnosis,
            weak_concepts=weak_concepts,
            interview_review_suggestion=suggestion,
            questions_to_revisit=questions,
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
            raw_payload={
                "title": title,
                "section": request.section,
                "priority": "normal",
                "summary": f"Ошибок: {len(request.mistakes)} из {request.total_count}.",
                "diagnosis": diagnosis,
                "weak_concepts": weak_concepts,
                "interview_review_suggestion": suggestion,
                "questions_to_revisit": questions,
            },
        )


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class ClaudeCliMistakeReviewAgent:
    provider = "claude_cli_mistake_review"
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        *,
        claude_bin: str = "claude",
        oauth_token: str = "",
        model: str = "",
        timeout_seconds: int = 180,
        allow_paid_api: bool = False,
        run_command: RunCommand | None = None,
        usage_recorder: LlmUsageRecorder | None = None,
    ):
        self.claude_bin = claude_bin
        self.oauth_token = oauth_token
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.allow_paid_api = allow_paid_api
        self._run_command = run_command or subprocess.run
        self.usage_recorder = usage_recorder or NoopLlmUsageRecorder()

    def analyze(self, request: MistakeReviewInput) -> MistakeReviewResult:
        started = time.perf_counter()
        system_prompt = _system_prompt()
        user_prompt = _user_prompt(request)
        cmd = [
            self.claude_bin,
            "--print",
            "--append-system-prompt",
            system_prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(MISTAKE_REVIEW_JSON_SCHEMA, ensure_ascii=False),
            "--no-session-persistence",
        ]
        if self.model:
            cmd.extend(["--model", self.model])

        log.info(
            "Mistake review agent started provider=%s session_id=%s mistakes=%s timeout_seconds=%s model=%s",
            self.provider,
            request.quiz_session_id,
            len(request.mistakes),
            self.timeout_seconds,
            self.model or "-",
        )
        try:
            log.info(
                "Mistake review agent request sent provider=%s waiting_for_response=true",
                self.provider,
            )
            proc = self._run_command(
                cmd,
                input=user_prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                cwd=str(PROJECT_ROOT),
                env=self._safe_env(),
            )
        except FileNotFoundError as exc:
            duration = time.perf_counter() - started
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=0,
                duration_sec=duration,
                success=False,
                error=f"Claude CLI not found: {self.claude_bin}",
                metadata={"stage": "start"},
            )
            raise MistakeReviewAgentError(f"Claude CLI not found: {self.claude_bin}") from exc
        except MistakeReviewAgentError as exc:
            duration = time.perf_counter() - started
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=0,
                duration_sec=duration,
                success=False,
                error=str(exc),
                metadata={"stage": "start"},
            )
            raise
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - started
            log.exception("Mistake review agent timed out timeout_seconds=%s", self.timeout_seconds)
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=len(_timeout_output(exc)),
                duration_sec=duration,
                success=False,
                error=f"Claude CLI timed out after {self.timeout_seconds} seconds",
                metadata={"stage": "timeout"},
            )
            raise MistakeReviewAgentError(
                f"Claude CLI timed out after {self.timeout_seconds} seconds"
            ) from exc

        duration = time.perf_counter() - started
        reported_usage = _claude_cli_reported_usage(proc.stdout)
        log.info(
            "Mistake review agent CLI finished returncode=%s duration_sec=%.1f stdout_chars=%s stderr_chars=%s",
            proc.returncode,
            duration,
            len(proc.stdout or ""),
            len(proc.stderr or ""),
        )
        if proc.returncode != 0:
            detail = _preview(proc.stderr or proc.stdout)
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=len((proc.stdout or "") + (proc.stderr or "")),
                duration_sec=duration,
                success=False,
                error=detail or f"Claude CLI failed with returncode {proc.returncode}",
                reported_usage=reported_usage,
                metadata={"stage": "cli", "returncode": proc.returncode},
            )
            raise MistakeReviewAgentError(
                "Claude CLI failed while analyzing quiz mistakes"
                + (f": {detail}" if detail else "")
            )

        try:
            payload = _extract_payload(proc.stdout)
        except MistakeReviewAgentError as exc:
            log.warning(
                "Mistake review agent returned non-JSON output stdout_preview=%r stderr_preview=%r",
                _preview(proc.stdout),
                _preview(proc.stderr),
            )
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=len(proc.stdout or ""),
                duration_sec=duration,
                success=False,
                error=str(exc),
                reported_usage=reported_usage,
                metadata={"stage": "parse"},
            )
            raise

        result = _result_from_payload(payload, request, self.provider, self.model, self.prompt_version)
        log.info(
            "Mistake review agent parsed title=%s priority=%s weak_concepts=%s duration_sec=%.1f",
            result.title,
            result.priority,
            len(result.weak_concepts),
            duration,
        )
        self._record_usage(
            request=request,
            input_chars=len(system_prompt) + len(user_prompt),
            output_chars=len(proc.stdout or ""),
            duration_sec=duration,
            success=True,
            reported_usage=reported_usage,
            metadata={
                "stage": "success",
                "title": result.title,
                "priority": result.priority,
                "mistake_count": len(request.mistakes),
            },
        )
        return result

    def _safe_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if not self.allow_paid_api:
            for name in PAID_API_ENV_VARS:
                env.pop(name, None)
            if not self.oauth_token:
                raise MistakeReviewAgentError(
                    "CLAUDE_CODE_OAUTH_TOKEN is required when ALLOW_PAID_API=false"
                )
        if self.oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token
        return env

    def _record_usage(
        self,
        *,
        request: MistakeReviewInput,
        input_chars: int,
        output_chars: int,
        duration_sec: float,
        success: bool,
        error: str = "",
        reported_usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event_metadata = {
            "quiz_session_id": request.quiz_session_id,
            "topic_id": request.topic_id,
            "mistake_count": len(request.mistakes),
        }
        usage = reported_usage or {}
        reported_metadata = usage.get("metadata")
        if isinstance(reported_metadata, dict):
            event_metadata.update(reported_metadata)
        if metadata:
            event_metadata.update(metadata)
        try:
            self.usage_recorder.record(
                provider=self.provider,
                feature="mistake_review_analysis",
                model=self.model,
                prompt_version=self.prompt_version,
                request_label=request.topic_title[:120],
                input_chars=input_chars,
                output_chars=output_chars,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                total_tokens=usage.get("total_tokens"),
                estimated_usd=usage.get("estimated_usd"),
                usage_source=str(usage.get("usage_source") or "estimated"),
                duration_ms=int(duration_sec * 1000),
                success=success,
                error=error,
                metadata=event_metadata,
            )
        except Exception:
            log.exception("Failed to record LLM usage for mistake review agent")


def _system_prompt() -> str:
    return (
        "Ты аналитик ошибок LearnKeeper.\n"
        "Пользователь прошел quiz по материалам interview-review и ошибся в части вопросов.\n"
        "Твоя задача: вернуть краткий, но полезный отчет для дальнейшей ручной проработки.\n\n"
        "Жесткие правила:\n"
        "- пиши максимально сжато и по делу: без воды, вступлений и повторов;\n"
        "- НЕ изменяй файлы;\n"
        "- НЕ предлагай git/diff/commit;\n"
        "- НЕ веди диалог и НЕ задавай уточняющих вопросов;\n"
        "- НЕ пиши длинную лекцию;\n"
        "- анализируй только JSON, который получил на вход;\n"
        "- верни только JSON по schema.\n\n"
        "Отчет должен помогать понять не просто 'какой ответ правильный', а какой пробел стоит "
        "потом руками доработать в interview-review.\n"
        "priority=high ставь, если ошибка показывает базовое непонимание темы или несколько ошибок "
        "об одном концепте; normal для обычной доработки; low для единичной неточности.\n"
    )


def _user_prompt(request: MistakeReviewInput) -> str:
    payload = json.dumps(asdict(request), ensure_ascii=False)
    return (
        "Разбери ошибки quiz-сессии LearnKeeper и верни JSON-отчет. Пиши кратко.\n\n"
        f"QUIZ_MISTAKES_JSON:\n{payload}\n\n"
        "Лимиты длины (держись в пределах, не превышай):\n"
        "- title: до 80 символов;\n"
        "- summary: 1-2 предложения, до 250 символов;\n"
        "- diagnosis: один абзац, 2-4 предложения, до 500 символов;\n"
        "- weak_concepts: 3-6 коротких пунктов;\n"
        "- interview_review_suggestion.details: 1-2 предложения, до 250 символов;\n"
        "- questions_to_revisit: только реально важные вопросы; в каждом missed_point, "
        "correct_idea и practice_prompt — по одному короткому предложению.\n\n"
        "Смысл полей:\n"
        "- title: название отчета;\n"
        "- section: блок/раздел, куда логично отнести проработку;\n"
        "- priority: low|normal|high;\n"
        "- summary: короткая выжимка;\n"
        "- diagnosis: суть пробела;\n"
        "- weak_concepts: конкретные слабые понятия;\n"
        "- interview_review_suggestion: что потом руками добавить/усилить в interview-review;\n"
        "- questions_to_revisit: что было упущено и как коротко потренировать.\n"
    )


def _extract_payload(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise MistakeReviewAgentError("Claude CLI returned empty output")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = json.loads(_json_object_slice(text))
    if not isinstance(raw, dict):
        raise MistakeReviewAgentError("Claude CLI output must be a JSON object")
    return _unwrap_payload(raw)


def _unwrap_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if "title" in raw and "diagnosis" in raw:
        return raw
    result = raw.get("result")
    if isinstance(result, dict):
        return _unwrap_payload(result)
    if isinstance(result, str) and result.strip():
        nested = json.loads(_json_object_slice(result))
        if isinstance(nested, dict):
            return _unwrap_payload(nested)
    content = raw.get("content")
    if isinstance(content, list):
        joined = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict)
        ).strip()
        if joined:
            nested = json.loads(_json_object_slice(joined))
            if isinstance(nested, dict):
                return _unwrap_payload(nested)
    raise MistakeReviewAgentError("Claude CLI JSON output does not contain mistake report payload")


def _json_object_slice(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"```$", "", clean).strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise MistakeReviewAgentError("Could not find JSON object in Claude CLI output")
    return clean[start : end + 1]


def _result_from_payload(
    payload: dict[str, Any],
    request: MistakeReviewInput,
    provider: str,
    model: str,
    prompt_version: str,
) -> MistakeReviewResult:
    title = _clean_inline(str(payload.get("title") or "")) or f"Разбор ошибок: {request.topic_title}"
    section = _clean_inline(str(payload.get("section") or "")) or request.section
    priority = _clean_inline(str(payload.get("priority") or "normal")).lower()
    if priority not in PRIORITIES:
        priority = "normal"
    summary = _clean_inline(str(payload.get("summary") or ""))
    if not summary:
        summary = f"Ошибок: {len(request.mistakes)} из {request.total_count}."
    diagnosis = str(payload.get("diagnosis") or "").strip()
    if not diagnosis:
        diagnosis = "Агент не дал диагноз. Проверь ошибочные вопросы и объяснения в отчете."
    weak_concepts = [
        _clean_inline(str(item))
        for item in _as_list(payload.get("weak_concepts"))
        if _clean_inline(str(item))
    ][:12]
    if not weak_concepts:
        weak_concepts = _weak_concepts_from_mistakes(request.mistakes)
    suggestion = payload.get("interview_review_suggestion")
    if not isinstance(suggestion, dict):
        suggestion = {}
    suggestion.setdefault("title", title)
    suggestion.setdefault("target_section", section)
    suggestion.setdefault("details", "Дополнить материалы по ошибочным вопросам.")
    questions = [
        item
        for item in _as_list(payload.get("questions_to_revisit"))
        if isinstance(item, dict)
    ][:10]
    return MistakeReviewResult(
        title=title,
        section=section,
        priority=priority,
        summary=summary,
        diagnosis=diagnosis,
        weak_concepts=weak_concepts,
        interview_review_suggestion=suggestion,
        questions_to_revisit=questions,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        raw_payload=payload,
    )


def _weak_concepts_from_mistakes(mistakes: list[dict[str, Any]]) -> list[str]:
    concepts: list[str] = []
    for item in mistakes[:6]:
        refs = item.get("source_refs")
        if isinstance(refs, list) and refs:
            concepts.append(str(refs[0]))
            continue
        question = _clean_inline(str(item.get("question") or ""))
        if question:
            concepts.append(question[:90])
    return concepts or ["Ошибочные вопросы quiz-сессии"]


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).strip(" .!?,:;\"'«»")


def _preview(value: str | None, *, limit: int = 800) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    parts: list[str] = []
    for value in (exc.stdout, exc.stderr):
        if isinstance(value, bytes):
            parts.append(value.decode(errors="ignore"))
        elif value:
            parts.append(str(value))
    return "".join(parts)
