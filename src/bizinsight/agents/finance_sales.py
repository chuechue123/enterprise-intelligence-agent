"""Finance and sales analysis Worker."""

from bizinsight.agents.worker_base import WorkerBase
from bizinsight.schemas import WorkerName


class FinanceSalesAgent(WorkerBase):
    """Analyze revenue, margin, collections and sales conversion."""

    worker_name = WorkerName.FINANCE_SALES
    allowed_datasets = frozenset(
        {"contracts", "customers", "opportunities", "payments"},
    )
    allowed_metrics = frozenset({"gross_margin", "revenue", "win_rate"})
    domain_prompt_filename = "finance_sales.md"
