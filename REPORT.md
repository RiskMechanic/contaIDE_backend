# Technical Report — contaIDEv2

Date: 2025-12-14

This document summarizes the current codebase, architecture, data model, test coverage, notable issues, and recommended next steps to bring the project to production readiness.

## Project Overview
- Purpose: Lightweight enterprise-grade accounting backend (journal / prima nota).
- Languages: Python (typing hints, dataclasses, sqlite3 as default DB).
- Key features implemented: validation rules, posting engine with atomic protocol allocation, idempotence registry, audit log with chained hashes, period management, simple accounting services (sales, purchases, cash, bank fees), and a test-suite covering validation and posting flows.

## High-level Architecture
- `core/`: Domain model (`models.py`), validator rules (`validator.py`), posting engine (`posting_engine.py`) and helpers.
- `kernel/`: Adapters / orchestration — `AccountingKernel` and `PosterAdapter` wire DB-backed repos to `PostingEngine`.
- `db/`: `DBManager` creates/initializes schema (SQLite), runs migrations and provides transactional helpers.
- `services/`: Higher-level user-facing facades (e.g., `LedgerService`, `ClosuresService`, `AuditService`, reporting helpers).
- `parser/`: (intended) DSL parser (currently empty/not implemented).
- `tests/`: PyTest-based test-suite covering validation, posting flows, idempotence, reversals and DB bootstrap.

## Data Model & DB Schema (important tables)
- `accounts`: chart of accounts (seeded by `db/chart_of_accounts.sql`).
- `periods` / `period_locks`: fiscal period registry.
- `entries`: journal entries (metadata + protocol and optional tax attributes).
- `entry_lines`: integer cents lines (constraints enforce not both dare/avere > 0).
- `protocol_counters`: per-(year, series) counters for protocol allocation.
- `idempotence`: key → payload_hash → entry_id mapping for safe retries.
- `audit_log`: payloads + prev/curr hash chain for tamper evidence.

Important behaviour:
- Protocol allocation is atomic via `protocol_counters` updates inside a DB transaction (implemented in `PostingEngine._next_protocol`).
- Idempotence: before creating entries, a content-hash is stored under a provided key; retries with the same payload return the original entry; mismatched payload yields an idempotence conflict.
- Audit: serialized payloads are hashed and chained (`prev_hash` / `curr_hash`) to detect tampering.

## Key Code Paths
- Posting flow: `services.LedgerService` → `kernel.PosterAdapter` → `core.PostingEngine.post()`
  - Validation via `core.validator.validate()` (uses DB-backed repos for account/period/entry checks).
  - Atomic transaction: protocol allocation, insert `entries`, `entry_lines`, `entry_reversals`, audit log, store idempotence record.

## Tests and Current Test Strategy
- Tests use a fresh shared in-memory SQLite DB per test via `file:memdb_...?mode=memory&cache=shared` and `DBManager.configure()`.
- Test coverage focuses on:
  - Validation rules (balancing, negative amounts, ambiguous or empty lines, account existence, period open, VAT consistency).
  - Posting happy path (protocol format, persistent lines and entry fields).
  - Protocol incrementing and idempotence behavior.
  - Reversal flow and audit chain verification.

Notes about running tests locally:
- The repository does not include a `requirements.txt` or `pyproject.toml`; ensure `pytest` is installed (e.g. `pip install pytest`) before running `pytest -q`.

## Notable Findings / Issues
1. Empty parser: `parser/dsl_parser.py` is empty — DSL parsing is not implemented.
2. Missing enum member: `kernel/poster_adapter.py` uses `ErrorCode.INVALID_INPUT`, but `ErrorCode` (in `core/models.py`) does not define `INVALID_INPUT`. This is a likely runtime error path (AttributeError) when `PosterAdapter.post_entry()` is called with invalid input. Add `INVALID_INPUT` to `ErrorCode` or change `PosterAdapter` to use an existing code.
3. Test runner: in this environment `pytest` wasn't available; add a `requirements.txt` or `pyproject.toml` to ease reproducible setup and CI.
4. Small inconsistency: tests sometimes compare error codes via string equality (e.g., `e.code == "UNBALANCED"`). `LedgerError.code` is an `ErrorCode` enum; comparing Enum to string can be brittle in some contexts. Tests currently work (enum is a `str` subclass), but keep an eye on explicit conversions when serializing error responses.
5. Parser and CLI: `main.py` contains a `demo_postings()` example; there is no CLI or HTTP surface. If you plan to expose the service, add a small API or CLI harness.

## Recommended Next Steps (prioritized)
1. Fix the `INVALID_INPUT` error: add `INVALID_INPUT` to `core.models.ErrorCode` and add a unit test for invalid input path in `PosterAdapter`.
2. Implement or remove the empty parser (`parser/dsl_parser.py`) depending on the product scope.
3. Add `requirements.txt` (at minimum `pytest`) and a basic `README.md` with run/test instructions.
4. Add CI (GitHub Actions) that runs `flake8`/`ruff` and `pytest` on push/PR.
5. Add tests that assert expected behaviour of `AuditService.verify_chain()`, idempotence conflict paths, and concurrent posting (to stress protocol allocation).
6. Consider adding type checking (`mypy`) and basic linting to improve maintainability.

## How to run & reproduce locally
1. Create a venv and activate it.
2. Install `pytest` (and any other deps you add):

```bash
python -m pip install pytest
pytest -q
```

3. To run the simple demo in `main.py`:

```bash
python main.py
```

Note: `main.py` calls `DBManager.initialize()` which creates the SQLite database `contaIDE.db` in the working directory unless `DBManager.configure()` is called first with a different path.

## Files of interest (quick map)
- `main.py`: bootstrap and demo postings
- `core/models.py`: domain DTOs and `ErrorCode` enum
- `core/validator.py`: validation rules and composite `validate()`
- `core/posting_engine.py`: transactional posting logic, idempotence, protocol allocation, audit
- `db/db_manager.py`: DB connection pool, transactional helper, schema/migrations bootstrap
- `db/schema_accounting.sql`, `db/chart_of_accounts.sql`: DB schema & seed
- `kernel/*`: adapters and kernel orchestration
- `services/*`: higher-level operations and query repositories
- `tests/*`: pytest suite

## Suggested tasks you can assign to an AI agent
- Add `INVALID_INPUT` to `ErrorCode` and write a unit test for the invalid input branch.
- Implement a minimal `parser/dsl_parser.py` (or add a TODO and unit tests).
- Add `requirements.txt` (add at least `pytest`) and a `README.md` with quickstart commands.
- Add CI pipeline to run tests and linting on push.
- Optional: add `pyproject.toml` and `ruff`/`mypy` for code quality.

---
If you want, I can now:
- Open a PR to add `INVALID_INPUT` and tests (small, targeted fix),
- Add a `requirements.txt` and a `README.md`, or
- Implement a minimal DSL parser skeleton and tests.

Tell me which of the next steps you want me to implement first and I will proceed.
