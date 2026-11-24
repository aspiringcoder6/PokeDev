# Historical orchestrator compiler fixtures

Frozen copies from `agentHarness` at `bd75307`:

- `adlc_components/flow/orchestrator.json`
- `adlc_components/flow/orchestrator-blueprint.json`

Main removed the old runtime examples. The compiler migration regression still needs both original JSON snapshots, so they are retained here as test inputs. The test checks that the legacy source remains unchanged and the migrated workflow compiles. Neither file authorizes a model call or deployment.
