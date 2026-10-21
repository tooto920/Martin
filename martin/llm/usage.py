"""Metadata-only usage ledger. Estimates never represent the provider balance."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone


class UsageLedger:
    def __init__(self, path, settings):
        self.path = path
        self.settings = settings
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS usage (id TEXT PRIMARY KEY, day TEXT, model TEXT, status TEXT, input INTEGER, output INTEGER, cached INTEGER, cost REAL, reserve REAL, metrics TEXT)"
            )
            if "reserved_tokens" not in {r[1] for r in db.execute("PRAGMA table_info(usage)")}:
                db.execute("ALTER TABLE usage ADD COLUMN reserved_tokens INTEGER DEFAULT 0")

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def begin(self, request_id, model, payload):
        from martin.llm.client import OllamaError

        if not (model.endswith(":cloud") or "-cloud" in model):
            return
        now = datetime.now(timezone.utc).isoformat()[:10]
        rates = self.settings.model_rates.get(model)
        # UTF-8 bytes are a conservative text token estimate, not API usage.
        upper = len(json.dumps(payload.get("messages", []), ensure_ascii=False).encode("utf8"))
        output = max(1, int(payload.get("options", {}).get("num_predict", 2048)))
        reserve = (upper * rates[0] + output * rates[1]) / 1e6 if rates else None
        with self._lock, self._db() as db:
            day = db.execute(
                "SELECT count(*),coalesce(sum(CASE WHEN input IS NULL OR output IS NULL THEN reserved_tokens ELSE input+output END),0),coalesce(sum(coalesce(cost,reserve)),0) FROM usage WHERE day=?",
                (now,),
            ).fetchone()
            month = db.execute(
                "SELECT coalesce(sum(coalesce(cost,reserve)),0) FROM usage WHERE substr(day,1,7)=?",
                (now[:7],),
            ).fetchone()[0]
            s = self.settings
            if s.daily_request_limit and day[0] >= s.daily_request_limit:
                raise OllamaError("Dosažen místní denní limit cloudových požadavků.", kind="budget")
            if s.daily_token_limit and day[1] + upper + output > s.daily_token_limit:
                raise OllamaError(
                    "Požadavek by překročil místní denní tokenový limit.", kind="budget"
                )
            if (s.daily_budget_usd or s.monthly_budget_usd) and (
                reserve is None or any(m.get("images") for m in payload.get("messages", []))
            ):
                raise OllamaError(
                    "Pro tento požadavek nelze předem spolehlivě odhadnout cenu. Uprav místní rozpočet nebo sazby.",
                    kind="budget",
                )
            if (s.daily_budget_usd and day[2] + reserve > s.daily_budget_usd) or (
                s.monthly_budget_usd and month + reserve > s.monthly_budget_usd
            ):
                raise OllamaError(
                    "Požadavek by překročil místní odhadovaný rozpočet.", kind="budget"
                )
            db.execute(
                "INSERT INTO usage (id,day,model,status,reserve,metrics,reserved_tokens) VALUES (?,?,?,?,?,?,?)",
                (request_id, now, model, "pending", reserve, "{}", upper + output),
            )

    def finish(self, data):
        rates = self.settings.model_rates.get(data["model"])
        inp, out, cached = (
            data.get(k) for k in ("prompt_eval_count", "eval_count", "prompt_eval_cached_count")
        )
        cost = None
        if inp is not None and out is not None and rates:
            cached = min(inp, cached or 0)
            cost = ((inp - cached) * rates[0] + out * rates[1] + cached * rates[2]) / 1e6
        safe = {k: v for k, v in data.items() if k not in ("error_message",)}
        safe.update(estimated_usd=cost, rates_date=self.settings.rates_date)
        with self._lock, self._db() as db:
            db.execute(
                "UPDATE usage SET status=?,input=?,output=?,cached=?,cost=?,metrics=? WHERE id=?",
                (data["status"], inp, out, cached, cost, json.dumps(safe), data["request_id"]),
            )

    def snapshot(self):
        today = datetime.now(timezone.utc).isoformat()[:10]
        with self._db() as db:

            def total(where, key):
                r = db.execute(
                    "SELECT count(*),sum(input),sum(output),sum(cost),sum(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) FROM usage WHERE "
                    + where,
                    (key,),
                ).fetchone()
                return dict(
                    requests=r[0],
                    input_tokens=r[1],
                    output_tokens=r[2],
                    estimated_usd=r[3],
                    unknown_cost_requests=r[4] or 0,
                )

            last = db.execute("SELECT metrics FROM usage ORDER BY rowid DESC LIMIT 1").fetchone()
            return {
                "day": total("day=?", today),
                "month": total("substr(day,1,7)=?", today[:7]),
                "last": json.loads(last[0]) if last else {},
                "balance": None,
                "rates_date": self.settings.rates_date,
                "usage_url": "https://ollama.com/settings/usage",
            }
