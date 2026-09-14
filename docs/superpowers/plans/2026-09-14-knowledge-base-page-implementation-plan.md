# Knowledge Base Page Implementation Plan

1. Add typed document-list response models and deterministic index parsing in `bizinsight.web`.
2. Expose the read-only `/bizinsight/knowledge/documents` endpoint with search and pagination.
3. Serve `/knowledge` and connect the existing sidebar navigation to the new page.
4. Build the responsive document table, loading/empty/error states, search debounce, pagination, and safe index-detail menu.
5. Extend web tests for routing, data contracts, filtering, pagination, malformed indexes, and DOM behavior.
6. Run focused tests, Ruff, the complete offline suite, and desktop/mobile visual checks before committing.
