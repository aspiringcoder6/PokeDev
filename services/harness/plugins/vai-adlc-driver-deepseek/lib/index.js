import { DeepSeekHarnessExecutionDriver } from './driver.js'

export const name = 'vai-adlc-driver-deepseek'
export const inject = ['agents', 'agentDefaultModel']

export async function apply(ctx, config = {}) {
  const { createUserMessage } = await import('@deepseek-ai/dsh-llm')
  const driver = new DeepSeekHarnessExecutionDriver({
    agents: ctx.agents,
    agentDefaultModel: ctx.agentDefaultModel,
    createUserMessage,
    profiles: config.profiles ?? {},
  })
  ctx.on('user-questions/request', (request, next) => driver.handleUserQuestions(request, next), {
    global: true,
    prepend: true,
  })
  ctx.on('approval/request', (request, next) => driver.handleApprovalRequest(request, next), {
    global: true,
    prepend: true,
  })
  ctx.provide('adlcExecutionDriver', driver)
  ctx.effect?.(() => () => void driver.close())
  console.log('[vai-adlc-driver-deepseek] real DeepSeek session driver ready')
}
