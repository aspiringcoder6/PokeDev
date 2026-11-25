import { GitArtifactCollector } from './collector.js'

export const name = 'vai-adlc-artifacts-git'

export function apply(ctx, config = {}) {
  ctx.provide('adlcArtifactCollector', new GitArtifactCollector(config))
  console.log('[vai-adlc-artifacts-git] isolated Git artifact collector ready')
}
