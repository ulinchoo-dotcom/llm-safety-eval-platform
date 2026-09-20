"""Import benign fixtures, execute two simulated models, and save honest run reports."""

import asyncio
import json
from pathlib import Path

import httpx

from safety_eval.config import Settings


async def main():
    settings = Settings()
    headers = {"Authorization": f"Bearer {settings.api_token.get_secret_value()}"}
    batch = json.loads(Path("examples/benign-cases.json").read_text())
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8100", headers=headers, timeout=60
    ) as client:
        response = await client.post("/api/cases/import", json=batch)
        if response.status_code not in (201, 409):
            response.raise_for_status()
        Path("reports").mkdir(exist_ok=True)
        for model in ("demo-safe", "demo-overrefusal"):
            response = await client.post(
                "/api/runs/demo",
                json={"model": model, "case_codes": [case["case_code"] for case in batch["cases"]]},
            )
            response.raise_for_status()
            run_id = response.json()["run_id"]
            response = await client.get(f"/api/runs/{run_id}")
            response.raise_for_status()
            Path(f"reports/{model}.json").write_text(
                json.dumps(response.json(), ensure_ascii=False, indent=2)
            )
            print(
                f"{model}: {run_id}, {len(response.json()['results'])} results pending human review"
            )
    print("Reports saved locally. No live model was called and no safety score was fabricated.")


if __name__ == "__main__":
    asyncio.run(main())
