import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID, uuid4

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .db import migrate, open_pool
from .metrics import coverage, summarize
from .pipeline import DemoProvider, TokenBucket, make_graph
from .schemas import DemoRun, ImportCases, ReviewInput
from .taxonomy import ATTACKS, CATEGORIES, TAXONOMY, VERSION


def create_app(settings: Settings | None = None):
    config = settings or Settings()
    if len(
        config.api_token.get_secret_value()
    ) < 24 or config.api_token.get_secret_value().startswith("replace-"):
        raise ValueError("API_TOKEN must be a random value of at least 24 characters")

    @asynccontextmanager
    async def lifespan(app):
        pool = await open_pool(config.database_url.get_secret_value())
        try:
            await migrate(pool)
            app.state.pool = pool
            app.state.run_slots = asyncio.Semaphore(2)
            app.state.limiters = {
                model: TokenBucket(100, 10) for model in ("demo-safe", "demo-overrefusal")
            }
            yield
        finally:
            await pool.close()

    app = FastAPI(
        title="大模型安全评测平台",
        version="0.1.0",
        lifespan=lifespan,
        description="第一阶段开发版：用例管理与离线模拟评测。模拟结果不可用于模型安全验收。",
    )
    bearer = HTTPBearer(auto_error=False)

    async def authenticate(auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not auth or not secrets.compare_digest(
            auth.credentials, config.api_token.get_secret_value()
        ):
            raise HTTPException(
                401, "A valid bearer token is required", headers={"WWW-Authenticate": "Bearer"}
            )

    secured = [Depends(authenticate)]

    @app.get("/health", tags=["服务状态"])
    async def health():
        await app.state.pool.fetchval("SELECT 1")
        return {"status": "ok", "mode": "development", "version": "0.1.0"}

    @app.get("/api/taxonomy", dependencies=secured, tags=["分类体系"])
    async def taxonomy():
        return TAXONOMY

    @app.post("/api/cases/import", dependencies=secured, tags=["用例库"], status_code=201)
    async def import_cases(batch: ImportCases):
        records = [case.model_dump() for case in batch.cases]
        codes = {case["case_code"] for case in records}
        parents = {case["parent_case_code"] for case in records if case["parent_case_code"]}
        # Validate ancestry even when both parent and child arrive in the same transaction.
        parent_map = {case["case_code"]: case["parent_case_code"] for case in records}
        for code in codes:
            visited = set()
            current = code
            while parent_map.get(current):
                if current in visited:
                    raise HTTPException(422, "parent cycle detected")
                visited.add(current)
                current = parent_map[current]
        async with app.state.pool.acquire() as conn, conn.transaction():
            existing = set(
                await conn.fetchval(
                    "SELECT coalesce(array_agg(case_code), ARRAY[]::text[]) FROM eval_cases WHERE case_code=ANY($1::text[])",
                    list(parents - codes),
                )
            )
            missing = parents - codes - existing
            if missing:
                raise HTTPException(422, {"missing_parents": sorted(missing)})
            try:
                await conn.executemany(
                    "INSERT INTO eval_cases(case_code,payload) VALUES($1,$2)",
                    [(case["case_code"], case) for case in records],
                )
            except asyncpg.UniqueViolationError:
                raise HTTPException(409, "case_code already exists; no records imported") from None
        return {"imported": len(records), "label_verified": False}

    @app.get("/api/cases", dependencies=secured, tags=["用例库"])
    async def list_cases(
        risk_category: str | None = None,
        attack_type: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
    ):
        if risk_category is not None and risk_category not in CATEGORIES:
            raise HTTPException(422, "unknown category")
        if attack_type is not None and attack_type not in ATTACKS:
            raise HTTPException(422, "unknown attack type")
        where = "WHERE ($1::text IS NULL OR payload->>'risk_category'=$1) AND ($2::text IS NULL OR payload->>'attack_type'=$2)"
        async with app.state.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT count(*) FROM eval_cases " + where, risk_category, attack_type
            )
            rows = await conn.fetch(
                "SELECT payload,label_verified FROM eval_cases "
                + where
                + " ORDER BY case_code OFFSET $3 LIMIT $4",
                risk_category,
                attack_type,
                offset,
                limit,
            )
        return {
            "total": total,
            "items": [{**r["payload"], "label_verified": r["label_verified"]} for r in rows],
        }

    @app.get("/api/coverage", dependencies=secured, tags=["用例库"])
    async def get_coverage():
        rows = await app.state.pool.fetch("SELECT payload,label_verified FROM eval_cases")
        return coverage([{**r["payload"], "label_verified": r["label_verified"]} for r in rows])

    @app.post("/api/runs/demo", dependencies=secured, tags=["离线演示"], status_code=201)
    async def run_demo(request: DemoRun):
        # Bounded synchronous HTTP operation for development; durable job workers are M3 work.
        async with app.state.run_slots:
            rows = await app.state.pool.fetch(
                "SELECT case_code,payload FROM eval_cases WHERE case_code=ANY($1::text[])",
                request.case_codes,
            )
            mapping = {r["case_code"]: r["payload"] for r in rows}
            missing = set(request.case_codes) - set(mapping)
            if missing:
                raise HTTPException(404, {"missing_cases": sorted(missing)})
            cases = [mapping[code] for code in request.case_codes]
            run_id = uuid4()
            await app.state.pool.execute(
                "INSERT INTO eval_runs(id,model,mode,prompt_version,handbook_version,case_snapshot,status) VALUES($1,$2,'demo',$3,$4,$5,'running')",
                run_id,
                request.model,
                request.prompt_version,
                VERSION,
                cases,
            )
            graph = make_graph(DemoProvider(request.model), app.state.limiters[request.model])
            semaphore = asyncio.Semaphore(4)

            async def evaluate(case):
                async with semaphore:
                    outcome = await graph.ainvoke({"case": case})
                    result = outcome["result"]
                    result.update(prompt_version=request.prompt_version, handbook_version=VERSION)
                    for call in result["attempts"]:
                        call.update(prompt_version=request.prompt_version, handbook_version=VERSION)
                    return (uuid4(), run_id, case["case_code"], result)

            try:
                results = await asyncio.gather(*(evaluate(case) for case in cases))
                async with app.state.pool.acquire() as conn, conn.transaction():
                    await conn.executemany(
                        "INSERT INTO judge_results(id,run_id,case_code,payload) VALUES($1,$2,$3,$4)",
                        results,
                    )
                    await conn.execute(
                        "UPDATE eval_runs SET status='pending_review',finished_at=now() WHERE id=$1",
                        run_id,
                    )
            except BaseException:
                await app.state.pool.execute(
                    "UPDATE eval_runs SET status='failed',finished_at=now() WHERE id=$1", run_id
                )
                raise
            return {
                "run_id": str(run_id),
                "mode": "demo",
                "status": "pending_review",
                "case_count": len(cases),
            }

    @app.get("/api/runs", dependencies=secured, tags=["离线演示"])
    async def list_runs():
        rows = await app.state.pool.fetch(
            "SELECT id,model,mode,status,started_at,finished_at FROM eval_runs ORDER BY started_at DESC LIMIT 100"
        )
        return [dict(row) for row in rows]

    @app.get("/api/runs/{run_id}", dependencies=secured, tags=["离线演示"])
    async def get_run(run_id: UUID):
        # Read run state and review overlay in one consistent snapshot.
        async with (
            app.state.pool.acquire() as conn,
            conn.transaction(isolation="repeatable_read", readonly=True),
        ):
            run = await conn.fetchrow("SELECT * FROM eval_runs WHERE id=$1", run_id)
            if run is None:
                raise HTTPException(404, "run not found")
            rows = await conn.fetch(
                "SELECT j.id,j.payload,r.payload AS review FROM judge_results j LEFT JOIN reviews r ON r.result_id=j.id WHERE j.run_id=$1 ORDER BY j.case_code",
                run_id,
            )
        results = []
        for row in rows:
            result = {**row["payload"], "id": str(row["id"]), "human_review": row["review"]}
            if row["review"]:
                result.update(
                    status="reviewed",
                    passed=row["review"]["passed"],
                    refused=row["review"]["refused"],
                    severity=row["review"]["severity"],
                    attack_succeeded=row["review"]["attack_succeeded"],
                )
            results.append(result)
        return {**dict(run), "results": results, "metrics": summarize(results)}

    @app.get("/api/reviews/pending", dependencies=secured, tags=["人工复核"])
    async def pending_reviews():
        rows = await app.state.pool.fetch(
            "SELECT j.id,j.run_id,j.case_code,j.payload FROM judge_results j LEFT JOIN reviews r ON r.result_id=j.id WHERE r.id IS NULL AND j.payload->>'status'='pending_review' ORDER BY j.run_id,j.case_code LIMIT 200"
        )
        return [dict(row) for row in rows]

    @app.post("/api/reviews/{result_id}", dependencies=secured, tags=["人工复核"], status_code=201)
    async def review(result_id: UUID, body: ReviewInput):
        async with app.state.pool.acquire() as conn, conn.transaction():
            result = await conn.fetchrow(
                "SELECT run_id,payload FROM judge_results WHERE id=$1", result_id
            )
            if result is None:
                raise HTTPException(404, "result not found")
            # Serialize reviews for the same run to keep the completion transition reliable.
            await conn.fetchrow("SELECT id FROM eval_runs WHERE id=$1 FOR UPDATE", result["run_id"])
            if body.attack_succeeded and result["payload"]["case_kind"] != "adversarial":
                raise HTTPException(422, "benign controls cannot be successful attacks")
            if result["payload"]["status"] != "pending_review":
                raise HTTPException(409, "call errors cannot be reviewed as safety outcomes")
            if await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM reviews WHERE result_id=$1)", result_id
            ):
                raise HTTPException(409, "result already reviewed; original decision is immutable")
            await conn.execute(
                "INSERT INTO reviews(id,result_id,reviewer_id,payload) VALUES($1,$2,$3,$4)",
                uuid4(),
                result_id,
                body.reviewer_id,
                body.model_dump(),
            )
            remaining = await conn.fetchval(
                "SELECT count(*) FROM judge_results j LEFT JOIN reviews r ON r.result_id=j.id WHERE j.run_id=$1 AND r.id IS NULL",
                result["run_id"],
            )
            if not remaining:
                await conn.execute(
                    "UPDATE eval_runs SET status='completed' WHERE id=$1", result["run_id"]
                )
        return {"result_id": str(result_id), "status": "reviewed"}

    return app
