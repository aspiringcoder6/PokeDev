# Lark intake contracts (package 0.2.0)

`pokedev_lark_contracts` is the authoritative wire model for LI-02. Install this package in both the Python 3.14 backend and Python 3.12 connector. Both deployments pin Pydantic 2.13.4. Import the same models; do not copy DTOs into either service.

Endpoints live under `/api/v1/adlc/intake/lark`. `/events`, `/deliveries/claim` and `/deliveries/{id}/result` require a dedicated connector bearer credential, scoped to the backend's configured app and tenant. User-facing linking uses a PokeDev session plus native password reauthentication; it does not share the connector credential.

`InboundMessage` preserves app, tenant, event, message, chat and sender IDs. Text is at most 20,000 characters. Pair commands carry a SHA256 digest and never the raw one-time code. Parent replies and unsupported input cannot become new LI-02 requirements. Extra fields, including a caller-selected PokeDev owner, are rejected.

`IngestReceipt` acknowledges a durable backend transaction. Duplicate event or message delivery replays the original outcome. Reusing an identity with different source data conflicts. `Delivery` contains a lease and stable UUID; only a definitive rejection permits bounded retry. `DeliveryResult` requires a provider message ID for DELIVERED. An expired or uncertain send is not automatically requeued. Backend API serialization and connector fixtures validate against these same classes.

## LI-03 wire v2

The historical directory remains stable for editable installations. The package root and unversioned connector endpoints retain wire v1; `pokedev_lark_contracts.v2` is the authority for LI-03. It adds distinct chat type, thread ID, mentioned open IDs and metadata-only group discovery. The `/v2/events`, `/v2/deliveries/claim` and `/v2/deliveries/{id}/result` endpoints use the v2 models. `APPENDED` records supplementary source evidence, while `TARGET_REQUIRED` makes no guessed binding. Neither changes or approves the brief.

V2 `Delivery` declares `reply_in_thread`; v1 claim excludes routes requiring v2. The new connector reads old journal payloads/results with their original models and submits their receipts to v1. Both result protocols normalize to the same stored delivery fingerprint. Do not upgrade a v1 journal entry in place or replay an unknown send.

`ConversationPage` is the authenticated private web response at `/requests/{id}/conversation`, with owner/project checks and pagination. Message, parent, root and thread remain separate opaque identifiers. Probe discovery has no text or pairing nonce. Group policies require an explicit project context (nullable) and default unmentioned-reply support to false. Both runtimes continue to pin Pydantic 2.13.4; no dependency on the agent readiness runtime is introduced.
