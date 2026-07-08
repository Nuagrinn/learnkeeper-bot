from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Row


@dataclass(frozen=True)
class CodingRep:
    id: str
    title: str
    prompt: str
    tag: str


# Small, single-sitting deliberate-practice exercises (20-30 min, one file, one
# success criterion), per long-term-learning-methodology.md's "Что делать с
# практикой кода". Static and free: no LLM call picks or grades these, so this
# feature costs nothing beyond a Telegram message. LearnKeeper never writes or
# checks the code itself — the point is the owner's own hands, not the bot's.
CODING_REPS: list[CodingRep] = [
    CodingRep(
        id="rate-limiter",
        title="TokenBucket.Allow",
        prompt=(
            "Реализуй TokenBucket.Allow(now time.Time) bool: лимит N токенов "
            "в секунду, восполнение по времени.\n"
            "Критерий успеха: 5 быстрых вызовов подряд — часть успешна, "
            "остальные получают отказ."
        ),
        tag="concurrency",
    ),
    CodingRep(
        id="group-by",
        title="GroupByCategory",
        prompt=(
            "Напиши GroupByCategory(items []Purchase) map[string][]Purchase — "
            "группировку по полю Category.\n"
            "Критерий успеха: корректно и без паники работает на пустом срезе."
        ),
        tag="maps",
    ),
    CodingRep(
        id="lru-cache",
        title="LRUCache на map + список",
        prompt=(
            "Реализуй LRUCache с Get/Put на map + двусвязном списке, лимит по "
            "размеру.\n"
            "Критерий успеха: при переполнении вытесняется наименее недавно "
            "использованный ключ."
        ),
        tag="maps",
    ),
    CodingRep(
        id="worker-pool-shutdown",
        title="Worker pool с graceful shutdown",
        prompt=(
            "Напиши worker pool на N горутин с graceful shutdown через "
            "context.\n"
            "Критерий успеха: при отмене все воркеры корректно завершаются, "
            "не теряя задачу, которую уже начали обрабатывать."
        ),
        tag="concurrency",
    ),
    CodingRep(
        id="context-leak",
        title="Найди и исправь context leak",
        prompt=(
            "Найди функцию (свою старую или из практики), где "
            "context.WithCancel создается, но cancel() не вызывается на всех "
            "путях выхода — особенно при раннем return из-за ошибки.\n"
            "Критерий успеха: cancel() вызывается через defer сразу после "
            "создания контекста."
        ),
        tag="context",
    ),
    CodingRep(
        id="fake-clock-test",
        title="Тест с fake clock",
        prompt=(
            "Напиши тест для функции с time.Now() внутри, используя интерфейс "
            "Clock с реализациями RealClock и FakeClock.\n"
            "Критерий успеха: тест детерминирован и не спит реальное время."
        ),
        tag="concurrency",
    ),
    CodingRep(
        id="inplace-filter",
        title="In-place фильтрация слайса",
        prompt=(
            "Реализуй Filter(s []int, keep func(int) bool) []int без "
            "аллокации нового underlying array — фильтруй на месте.\n"
            "Критерий успеха: используется только память исходного слайса."
        ),
        tag="slices",
    ),
    CodingRep(
        id="defensive-copy-bytes",
        title="Защитное копирование []byte",
        prompt=(
            "Напиши SafeCopy(b []byte) []byte — защитное копирование, чтобы "
            "вызывающий не мог изменить оригинал через возвращенный слайс.\n"
            "Критерий успеха: изменение результата не отражается на входном b."
        ),
        tag="slices",
    ),
    CodingRep(
        id="dedupe-slice",
        title="Unique без лишних аллокаций",
        prompt=(
            "Напиши Unique(s []int) []int, сохраняя порядок первого вхождения "
            "и используя не больше одной map под учет виденных значений.\n"
            "Критерий успеха: порядок сохранен, дубликаты убраны."
        ),
        tag="slices",
    ),
    CodingRep(
        id="retry-backoff",
        title="Retry с экспоненциальным backoff",
        prompt=(
            "Реализуй RetryWithBackoff(fn func() error, maxAttempts int) "
            "error с экспоненциальной задержкой между попытками.\n"
            "Критерий успеха: ранний выход при первом успехе, без лишнего "
            "ожидания."
        ),
        tag="concurrency",
    ),
    CodingRep(
        id="concurrent-counter",
        title="Mutex vs atomic счетчик",
        prompt=(
            "Реализуй потокобезопасный счетчик двумя способами: через "
            "sync.Mutex и через atomic.Int64.\n"
            "Критерий успеха: можешь объяснить словами, когда какой подход "
            "уместнее."
        ),
        tag="concurrency",
    ),
    CodingRep(
        id="debounce",
        title="Debounce-обертка",
        prompt=(
            "Напиши Debounce(fn func(), d time.Duration) func() — вызов fn "
            "откладывается, пока не пройдет d с последнего вызова обертки.\n"
            "Критерий успеха: серия быстрых вызовов дает один вызов fn."
        ),
        tag="concurrency",
    ),
    CodingRep(
        id="keyset-pagination",
        title="Keyset pagination вместо OFFSET",
        prompt=(
            "Спроектируй SQL keyset pagination (не OFFSET) для списка заказов "
            "по (created_at, id): следующая страница — через курсор, не "
            "номер страницы.\n"
            "Критерий успеха: запрос устойчив к вставке новых строк между "
            "запросами страниц."
        ),
        tag="db",
    ),
    CodingRep(
        id="predict-output",
        title="Что выведет код — без запуска",
        prompt=(
            "Открой любой review.md из Code Review Go или Базовый Go, найди "
            "пример «что выведет код» и реши его на бумаге, без запуска.\n"
            "Критерий успеха: потом проверь себя через go run — и если "
            "ошибся, зафиксируй это в журнале ошибок."
        ),
        tag="general",
    ),
]

_REPS_BY_ID = {rep.id: rep for rep in CODING_REPS}


def get_coding_rep(rep_id: str) -> CodingRep | None:
    return _REPS_BY_ID.get(rep_id)


@dataclass(frozen=True)
class CodingRepLogEntry:
    id: str
    rep_id: str
    rep_title: str
    status: str
    sent_at: datetime
    responded_at: datetime | None = None


def coding_rep_log_entry_from_row(row: Row) -> CodingRepLogEntry:
    return CodingRepLogEntry(
        id=row["id"],
        rep_id=row["rep_id"],
        rep_title=row["rep_title"],
        status=row["status"],
        sent_at=datetime.fromisoformat(row["sent_at"]),
        responded_at=(
            datetime.fromisoformat(row["responded_at"])
            if row["responded_at"]
            else None
        ),
    )
