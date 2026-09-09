"""Project delivery analysis Worker."""

from bizinsight.agents.worker_base import WorkerBase
from bizinsight.schemas import WorkerName


class DeliveryAgent(WorkerBase):
    """Analyze acceptance, delivery hours, customization and cost signals."""

    worker_name = WorkerName.DELIVERY
    allowed_datasets = frozenset({"contracts", "customers", "projects"})
    allowed_metrics = frozenset({"on_time_acceptance_rate"})
    domain_prompt_filename = "delivery.md"
