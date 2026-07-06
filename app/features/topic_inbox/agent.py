from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import PROJECT_ROOT
from app.features.llm_usage.service import LlmUsageRecorder, NoopLlmUsageRecorder
from app.features.quiz.generator import PAID_API_ENV_VARS, _claude_cli_reported_usage


log = logging.getLogger(__name__)

PROMPT_VERSION = "learnkeeper-topic-inbox-normalizer-v1"
AGENT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "section", "summary"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "section": {"type": "string"},
        "summary": {"type": "string"},
    },
}


@dataclass(frozen=True)
class TopicInboxAgentResult:
    raw_request: str
    title: str
    section: str
    summary: str
    provider: str
    model: str
    prompt_version: str = PROMPT_VERSION


class TopicInboxAgentError(RuntimeError):
    pass


class TopicInboxAgent(Protocol):
    provider: str
    model: str
    prompt_version: str

    def normalize(self, request: str) -> TopicInboxAgentResult:
        ...


class FakeTopicInboxAgent:
    provider = "fake"
    model = "fake"
    prompt_version = "fake-topic-inbox-normalizer-v1"

    def normalize(self, request: str) -> TopicInboxAgentResult:
        title, section = _basic_normalize(request)
        return TopicInboxAgentResult(
            raw_request=request,
            title=title,
            section=section,
            summary="Fake normalizer: сохранена очищенная формулировка без LLM.",
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
        )


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class ClaudeCliTopicInboxAgent:
    provider = "claude_cli_topic_inbox"
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        *,
        claude_bin: str = "claude",
        oauth_token: str = "",
        model: str = "",
        timeout_seconds: int = 120,
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

    def normalize(self, request: str) -> TopicInboxAgentResult:
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
            json.dumps(AGENT_JSON_SCHEMA, ensure_ascii=False),
            "--no-session-persistence",
        ]
        if self.model:
            cmd.extend(["--model", self.model])

        log.info(
            "Topic inbox normalizer started provider=%s request_len=%s timeout_seconds=%s model=%s",
            self.provider,
            len(request),
            self.timeout_seconds,
            self.model or "-",
        )
        try:
            log.info(
                "Topic inbox normalizer request sent provider=%s waiting_for_response=true",
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
            log.exception("Claude CLI executable was not found: %s", self.claude_bin)
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=0,
                duration_sec=time.perf_counter() - started,
                success=False,
                error=f"Claude CLI not found: {self.claude_bin}",
                metadata={"stage": "start"},
            )
            raise TopicInboxAgentError(f"Claude CLI not found: {self.claude_bin}") from exc
        except TopicInboxAgentError as exc:
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=0,
                duration_sec=time.perf_counter() - started,
                success=False,
                error=str(exc),
                metadata={"stage": "start"},
            )
            raise
        except subprocess.TimeoutExpired as exc:
            log.exception(
                "Topic inbox normalizer timed out timeout_seconds=%s",
                self.timeout_seconds,
            )
            self._record_usage(
                request=request,
                input_chars=len(system_prompt) + len(user_prompt),
                output_chars=len(_timeout_output(exc)),
                duration_sec=time.perf_counter() - started,
                success=False,
                error=f"Claude CLI timed out after {self.timeout_seconds} seconds",
                metadata={"stage": "timeout"},
            )
            raise TopicInboxAgentError(
                f"Claude CLI timed out after {self.timeout_seconds} seconds"
            ) from exc

        duration = time.perf_counter() - started
        reported_usage = _claude_cli_reported_usage(proc.stdout)
        log.info(
            "Topic inbox normalizer CLI finished returncode=%s duration_sec=%.1f stdout_chars=%s stderr_chars=%s",
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
            raise TopicInboxAgentError(
                "Claude CLI failed while normalizing topic inbox item"
                + (f": {detail}" if detail else "")
            )

        try:
            payload = _extract_payload(proc.stdout)
        except TopicInboxAgentError as exc:
            log.warning(
                "Topic inbox normalizer returned non-JSON output stdout_preview=%r stderr_preview=%r",
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

        title, fallback_section = _basic_normalize(request)
        normalized = _clean_inline(str(payload.get("title") or "")) or title
        section = _clean_inline(str(payload.get("section") or "")) or fallback_section
        section = _sanitize_section(section)
        normalized = _strip_section_prefix(normalized, section)
        normalized = _strip_meta_title_prefix(normalized)
        summary = _clean_inline(str(payload.get("summary") or ""))
        if not summary:
            summary = "Claude сформулировал идею для inbox."
        log.info(
            "Topic inbox normalizer parsed title=%s section=%s duration_sec=%.1f",
            normalized,
            section or "-",
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
                "title": normalized,
                "section": section,
            },
        )
        return TopicInboxAgentResult(
            raw_request=request,
            title=normalized,
            section=section,
            summary=summary,
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
        )

    def _safe_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if not self.allow_paid_api:
            for name in PAID_API_ENV_VARS:
                env.pop(name, None)
            if not self.oauth_token:
                raise TopicInboxAgentError(
                    "CLAUDE_CODE_OAUTH_TOKEN is required when ALLOW_PAID_API=false"
                )
        if self.oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token
        return env

    def _record_usage(
        self,
        *,
        request: str,
        input_chars: int,
        output_chars: int,
        duration_sec: float,
        success: bool,
        error: str = "",
        reported_usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event_metadata = {"request_len": len(request)}
        usage = reported_usage or {}
        reported_metadata = usage.get("metadata")
        if isinstance(reported_metadata, dict):
            event_metadata.update(reported_metadata)
        if metadata:
            event_metadata.update(metadata)
        try:
            self.usage_recorder.record(
                provider=self.provider,
                feature="topic_inbox_normalize",
                model=self.model,
                prompt_version=self.prompt_version,
                request_label=request[:120],
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
            log.exception("Failed to record LLM usage for topic inbox normalizer")


def _system_prompt() -> str:
    return (
        "Ты редактор inbox-идей LearnKeeper.\n"
        "Пользователь голосом или текстом быстро скидывает мысли на будущее: "
        "что изучить, почитать, реализовать, написать, доработать или проверить. "
        "Твоя задача: превратить сырую фразу в аккуратную, понятную идею для будущей ручной обработки.\n\n"
        "Жесткие правила:\n"
        "- НЕ анализируй репозиторий;\n"
        "- НЕ читай файлы;\n"
        "- НЕ проверяй, покрыта тема уже или нет;\n"
        "- НЕ предлагай diff, commit, git-команды или изменения файлов;\n"
        "- НЕ веди диалог и НЕ задавай уточняющих вопросов;\n"
        "- НЕ пиши в title служебные слова: 'нормализация', 'нормализовать', 'тема запроса', 'идея темы';\n"
        "- НЕ ставь section='inbox', 'topic', 'theme' или похожие технические слова.\n\n"
        "Верни только JSON по schema.\n\n"
        "Как формулировать title:\n"
        "- сохрани исходный смысл, не сужай идею до одного случайного термина;\n"
        "- title должен быть коротким, но полноценным: 4-12 слов;\n"
        "- если это учебная идея, начинай с действия: 'Изучить ...', 'Разобраться с ...';\n"
        "- если это книга/статья/курс, начинай с 'Почитать ...' или 'Пройти ...';\n"
        "- если это продуктовая/кодовая работа, начинай с 'Реализовать ...', 'Доработать ...', 'Написать ...';\n"
        "- можно сохранять формат 'область: конкретика', если так красивее.\n\n"
        "Как формулировать section:\n"
        "- используй мягкую категорию действия: Изучить, Почитать, Реализовать, Написать, Доработать, Проверить;\n"
        "- если пользователь явно назвал предметную область или блок, можно поставить ее: System Design, Базы данных, Go, Архитектура;\n"
        "- если не уверен, оставь пустую строку.\n\n"
        "Дополнительно:\n"
        "- убери слова команды: добавь, изучить, надо бы, новая тема, отдельный блок, нужно;\n"
        "- исправь очевидные STT-ошибки только если уверен;\n"
        "- сохрани технические термины: Go, PostgreSQL, Kafka, Outbox, CAP, pprof, rate limiter;\n"
        "- summary одним предложением объясняет, что потом сделать с идеей.\n\n"
        "Примеры:\n"
        "raw: 'Патерна отказа устойчивости рейт-лиметр'\n"
        'json: {"title":"Изучить rate limiter как паттерн отказоустойчивости","section":"Изучить","summary":"Разобрать назначение, алгоритмы и сценарии применения rate limiter в отказоустойчивых системах."}\n'
        "raw: 'надо почитать книгу про паттерны отказоустойчивости'\n"
        'json: {"title":"Почитать книгу про паттерны отказоустойчивости","section":"Почитать","summary":"Найти подходящую книгу или главы и вынести идеи в материалы."}\n'
        "raw: 'добавить фичу на выбор сложности теста'\n"
        'json: {"title":"Реализовать выбор сложности теста","section":"Реализовать","summary":"Продумать UX и добавить настройку сложности при запуске теста."}\n'
    )


def _user_prompt(request: str) -> str:
    payload = json.dumps({"raw_request": request}, ensure_ascii=False)
    return (
        "Сформулируй сырую inbox-идею LearnKeeper как понятную будущую задачу или тему.\n\n"
        f"REQUEST_JSON:\n{payload}\n\n"
        "Верни JSON вида:\n"
        '{"title":"...","section":"...","summary":"..."}'
    )


def _extract_payload(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise TopicInboxAgentError("Claude CLI returned empty output")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = json.loads(_json_object_slice(text))
    if not isinstance(raw, dict):
        raise TopicInboxAgentError("Claude CLI output must be a JSON object")
    return _unwrap_payload(raw)


def _unwrap_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if "title" in raw:
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
    raise TopicInboxAgentError("Claude CLI JSON output does not contain inbox payload")


def _json_object_slice(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"```$", "", clean).strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise TopicInboxAgentError("Could not find JSON object in Claude CLI output")
    return clean[start : end + 1]


def _basic_normalize(value: str) -> tuple[str, str]:
    clean = _clean_inline(value)
    clean = re.sub(
        r"^(?:давай\s+)?(?:добавь|добавить|создай|создать|изучить|изучи|надо бы|нужно)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(
        r"^(?:(?:новую|новый|отдельную|отдельный)\s+)?(?:тему|тема|блок|раздел)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    section = ""
    explicit = re.search(
        r"(?:^|\b)(?:(?:отдельный|новый)\s+)?(?:блок|раздел)\s+(.+?)(?:[:.;]|$)",
        value,
        flags=re.IGNORECASE,
    )
    if explicit:
        section = _clean_inline(explicit.group(1))
    elif ":" in clean:
        left, right = clean.split(":", 1)
        if 2 <= len(left.strip()) <= 80 and right.strip():
            section = _clean_inline(left)
            clean = _clean_inline(right)
    section = _sanitize_section(section)
    title = _strip_meta_title_prefix(_strip_section_prefix(clean, section))
    return title or _strip_meta_title_prefix(_clean_inline(value)), section[:80]


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).strip(" .!?,:;\"'«»")


def _strip_section_prefix(title: str, section: str) -> str:
    if not title or not section:
        return title
    pattern = rf"^{re.escape(section)}\s*[:\-—]\s*"
    stripped = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
    return stripped or title


def _sanitize_section(section: str) -> str:
    clean = _clean_inline(section)
    if clean.lower() in {"inbox", "topic", "theme", "тема", "идея", "темы", "идеи"}:
        return ""
    return clean[:80]


def _strip_meta_title_prefix(title: str) -> str:
    clean = _clean_inline(title)
    return re.sub(
        r"^(?:нормализац(?:ия|ию)\s+)?(?:темы|идеи|запроса)\s*[:\-—]\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip() or clean


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
