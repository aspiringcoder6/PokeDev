import { readFile, writeFile } from 'node:fs/promises';
import { digestInstalledPlugin } from '/app/plugins-source/vai-adlc-runtime/lib/plugin-integrity.js';

const root = '/app/plugins-source';
const ids = ['vai-adlc-runtime', 'vai-adlc-driver-deepseek', 'vai-adlc-verify-structured', 'vai-adlc-artifacts-git'];
const entries = [];
for (const id of ids) {
  const plugin = await digestInstalledPlugin(root, id);
  entries.push(`      - plugin_id: ${id}\n        version: "${plugin.version}"\n        content_digest: ${plugin.content_digest}\n        required: true`);
}
const file = `${root}/patch.yml`;
const patch = await readFile(file, 'utf8');
if (!patch.includes('      # GENERATED_PLUGIN_LOCK')) throw Error('Plugin lock marker missing');
await writeFile(file, patch.replace('      # GENERATED_PLUGIN_LOCK', '      pluginLock:\n' + entries.join('\n')));
