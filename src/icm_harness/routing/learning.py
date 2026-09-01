import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BetaPosterior:
    alpha: float
    beta: float
    observations: int

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def exploration_bonus(self) -> float:
        return math.sqrt(math.log(self.observations + 2.0) / (self.observations + 1.0))


class BayesianPerformanceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS performance (
                model TEXT NOT NULL,
                stage_ref TEXT NOT NULL,
                task_class TEXT NOT NULL,
                alpha REAL NOT NULL,
                beta REAL NOT NULL,
                observations INTEGER NOT NULL,
                PRIMARY KEY(model, stage_ref, task_class)
            )
            """)

    def posterior(
        self, model: str, stage_ref: str, task_class: str, prior_quality: float
    ) -> BetaPosterior:
        strength = 4.0
        prior_alpha = 1.0 + prior_quality * strength
        prior_beta = 1.0 + (1.0 - prior_quality) * strength
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """SELECT alpha, beta, observations FROM performance
                WHERE model=? AND stage_ref=? AND task_class=?""",
                (model, stage_ref, task_class),
            ).fetchone()
        return BetaPosterior(prior_alpha, prior_beta, 0) if row is None else BetaPosterior(*row)

    def update(
        self, model: str, stage_ref: str, task_class: str, success: bool, prior_quality: float
    ) -> None:
        cur = self.posterior(model, stage_ref, task_class, prior_quality)
        alpha = cur.alpha + (1.0 if success else 0.0)
        beta = cur.beta + (0.0 if success else 1.0)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
            INSERT INTO performance VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(model,stage_ref,task_class) DO UPDATE SET
            alpha=excluded.alpha,beta=excluded.beta,observations=excluded.observations
            """,
                (model, stage_ref, task_class, alpha, beta, cur.observations + 1),
            )
