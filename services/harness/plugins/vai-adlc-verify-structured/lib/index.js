export const name = 'vai-adlc-verify-structured'

const VERIFIER_REF = 'plugin:vai-adlc-verify-structured/0.1.0'

function utcNow() {
  return new Date().toISOString()
}

function verificationReport({ status, summary, startedAt }) {
  return {
    verifier_ref: VERIFIER_REF,
    status,
    checks: [{
      check_id: 'structured-result',
      status,
      summary,
      evidence_artifact_refs: [],
    }],
    evidence_artifact_refs: [],
    started_at: startedAt,
    completed_at: utcNow(),
  }
}

export function apply(ctx) {
  const verifier = {
    async verify({ request, output, startedAt }) {
      const expected = request?.result_schema_ref
      const sourcePatch = output?.outputs?.source_patch
      if (expected === 'adlc://schemas/source-patch/0.1' && (typeof sourcePatch !== 'string' || sourcePatch === '')) {
        return [verificationReport({
          status: 'FAILED',
          summary: 'The required source_patch output is missing.',
          startedAt,
        })]
      }
      if (output === null || typeof output !== 'object' || Array.isArray(output)) {
        return [verificationReport({
          status: 'FAILED',
          summary: 'The session output is not a structured object.',
          startedAt,
        })]
      }
      return [verificationReport({
        status: 'PASSED',
        summary: 'The result satisfies the configured structured-output boundary.',
        startedAt,
      })]
    },
  }
  ctx.provide('adlcVerifier', verifier)
  console.log(`[vai-adlc-verify-structured] verifier ready as ${VERIFIER_REF}`)
}
