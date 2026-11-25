import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

// Provider/model IDs are routing metadata. API keys stay in Harness Settings.
export function configurePatch(template, env) {
  const provider = (env.POKEDEV_HARNESS_PROVIDER ?? '').trim();
  const model = (env.POKEDEV_HARNESS_MODEL ?? '').trim();
  if (Boolean(provider) !== Boolean(model)) {
    throw Error('Set both POKEDEV_HARNESS_PROVIDER and POKEDEV_HARNESS_MODEL.');
  }
  for (const [marker, value] of [['__POKEDEV_PROVIDER__', provider], ['__POKEDEV_MODEL__', model]]) {
    if (!template.includes(`"${marker}"`)) throw Error(`Harness patch marker missing: ${marker}`);
    template = template.replaceAll(`"${marker}"`, JSON.stringify(value));
  }
  return template;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const template = await readFile('/app/plugins-source/patch.yml', 'utf8');
  await writeFile('/app/data/harness.patch.yml', configurePatch(template, process.env), { mode: 0o600 });
  console.log(process.env.POKEDEV_HARNESS_MODEL ? 'PokeDev execution model route configured.' :
    'PokeDev execution model pending: set POKEDEV_HARNESS_PROVIDER and POKEDEV_HARNESS_MODEL.');
}
