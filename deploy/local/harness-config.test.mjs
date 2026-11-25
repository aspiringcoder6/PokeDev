import { test } from 'node:test';
import assert from 'node:assert/strict';
import { configurePatch } from './harness-config.mjs';

const template = 'provider: "__POKEDEV_PROVIDER__"\nmodel: "__POKEDEV_MODEL__"';
test('route settings stay data even with YAML special characters', () => {
  const provider = 'custom: "my-provider"';
  const model = 'vendor/model\nwith-newline';
  const result = configurePatch(template, { POKEDEV_HARNESS_PROVIDER: provider, POKEDEV_HARNESS_MODEL: model });
  assert.equal(result, `provider: ${JSON.stringify(provider)}\nmodel: ${JSON.stringify(model)}`);
});
test('partly configured routes fail before starting the runtime', () => {
  assert.throws(() => configurePatch(template, { POKEDEV_HARNESS_PROVIDER: 'my-provider' }), /both/);
});
test('unconfigured routes remain empty until the user attaches a model', () => {
  assert.equal(configurePatch(template, {}), 'provider: ""\nmodel: ""');
});
