"""Customer, product usage and service analysis Worker."""

from bizinsight.agents.worker_base import WorkerBase
from bizinsight.schemas import WorkerName


class CustomerProductAgent(WorkerBase):
    """Jointly analyze subscriptions, usage, tickets and customer context."""

    worker_name = WorkerName.CUSTOMER_PRODUCT
    allowed_datasets = frozenset(
        {
            "contracts",
            "customers",
            "product_usage",
            "subscriptions",
            "support_tickets",
        },
    )
    allowed_metrics = frozenset({"renewal_rate"})
    domain_prompt_filename = "customer_product.md"
