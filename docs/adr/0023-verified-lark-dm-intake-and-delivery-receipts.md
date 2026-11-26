# ADR 0023 Verified Lark DM intake and delivery receipts

Date: 2026-11-26
Status: Accepted (automated, PostgreSQL, desktop and live DM intake checks)
Deciders: PokeDev maintainer request and implementation decisions within LI-02

## Context

LI-01 stores private requirements. LI-00 verified real Lark DM reception and a manual reply, but the receive-only probe does not authenticate a PokeDev owner or create requirements. `docs/inputTakingNotes.md` separates input normalization and human delivery from the readiness pipeline. The existing readiness and source-access modules implement the latter pipeline and remain disabled here.

## Decision

Use the existing PokeDev database for identity links, inbound receipts and outbound delivery intents. A user must reauthenticate their PokeDev account, obtain a short-lived one-time code, and send it from their Lark DM; store only its digest. Local auto-login alone never establishes an external identity. Derive project access from native PokeDev policy at creation and delivery time.

The optional connector journals normalized events before the SDK callback returns and transfers them to authenticated backend endpoints. The shared `pokedev-lark-contracts` package is the authoritative wire model on Python 3.12 and 3.14. Namespace deduplication by app, tenant and event/message identity. Persist the new intake, original source reference and outbox intent atomically.

Persist send intent before calling Lark. A lease whose send result is unknown becomes UNCONFIRMED and requires reconciliation; never silently send again. An accepted provider response can be submitted repeatedly as a delivery receipt without resending its message. New top-level text DMs create separate private requirements; threaded replies, cards, file extraction and agent questions are later slices.

## Alternatives considered

- Map all Lark users to the local auto-login account: simple setup but no proof of identity or ownership; rejected.
- Match display names or email: convenient but mutable and not proof of control; rejected.
- Put all business state in connector SQLite: fewer backend changes but splits authorization, migrations and requirement transactions; rejected. SQLite remains only the connector's durable transport journal.
- Retry every timed-out send: improves apparent availability but can duplicate human-facing messages; rejected. Unknown results stop for reconciliation.

## Consequences

The operator configures a dedicated connector credential, app/tenant allowlist and trusted PokeDev URL. Linking needs an explicit password check even when the local UI auto-logs in. Only text DM intake and receipts are enabled by LI-02; agents, source collection, approval and execution remain separate. Existing web/API consumers and `/api/v1/adlc` namespaces remain compatible.

## Migration and rollback

Add new tables after `li01a2b3c4d5`. Deploy the shared contract and backend before starting the connector. The default feature flag is off. Disabling it stops new transfers and claims, while durable journals, requirements and receipts remain. Stop the connector before recovery; preserve UNCONFIRMED deliveries and resolve them against Lark before an operator decides to retry. Do not roll back by deleting history.

## Validation

Backend regression (295 cases), connector/probe checks (22 cases), desktop component checks (7 cases), the production frontend build and an isolated PostgreSQL migration/pairing/delivery check passed. The local desktop form exposes the actual native account and requires its password.

On 2026-11-26 the user completed native reauthentication and sent the pairing command from Lark. The link was persisted with its one-time digest consumed. A subsequent user-sent test DM created exactly one private revision-1 intake owned by that linked account, retained the original source and matched the saved description. The connector journal accepted both events; both the linking confirmation and intake receipt have provider message receipts, DELIVERED state and backend acknowledgements. Reloading the desktop page displayed the new request and its content. These results do not establish SDK redelivery behavior or a measured end-to-end latency target. See the [LI-02 runbook](../operations/lark-li02.md).
