# Lark intake contract 0.1

`pokedev_lark_contracts` is the authoritative wire model for LI-02. Install this package in both the Python 3.14 backend and Python 3.12 connector. Both deployments pin Pydantic 2.13.4. Import the same models; do not copy DTOs into either service.

Endpoints live under `/api/v1/adlc/intake/lark`. `/events`, `/deliveries/claim` and `/deliveries/{id}/result` require a dedicated connector bearer credential, scoped to the backend's configured app and tenant. User-facing linking uses a PokeDev session plus native password reauthentication; it does not share the connector credential.

`InboundMessage` preserves app, tenant, event, message, chat and sender IDs. Text is at most 20,000 characters. Pair commands carry a SHA256 digest and never the raw one-time code. Parent replies and unsupported input cannot become new LI-02 requirements. Extra fields, including a caller-selected PokeDev owner, are rejected.

`IngestReceipt` acknowledges a durable backend transaction. Duplicate event or message delivery replays the original outcome. Reusing an identity with different source data conflicts. `Delivery` contains a lease and stable UUID; only a definitive rejection permits bounded retry. `DeliveryResult` requires a provider message ID for DELIVERED. An expired or uncertain send is not automatically requeued. Backend API serialization and connector fixtures validate against these same classes.
