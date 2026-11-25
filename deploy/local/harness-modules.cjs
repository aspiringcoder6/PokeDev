// Keep the stock runtime dependency graph; make native process types singleton.
const fs = require('node:fs');
const path = require('node:path');
const root = '/usr/local/lib/node_modules/@deepseek-ai';
const scope = path.join(root, 'dsh/node_modules/@deepseek-ai');
for (const base of ['dsh-base', 'dsh-sdk-minimal']) {
  const prefix = path.join(scope, base, 'node_modules/@deepseek-ai');
  const canonical = path.join(prefix, 'dsh-subprocess-local/node_modules/@deepseek-ai/dsh-win32-process');
  const duplicate = path.join(prefix, 'dsh-sandbox-local/node_modules/@deepseek-ai/dsh-sandbox-windows-acl/node_modules/@deepseek-ai/dsh-win32-process');
  if (fs.existsSync(canonical) && fs.existsSync(duplicate)) {
    if (require(path.join(canonical, 'package.json')).version !== require(path.join(duplicate, 'package.json')).version) {
      throw Error('Incompatible process modules; update the compatibility adapter.');
    }
    fs.rmSync(duplicate, { recursive: true });
    fs.symlinkSync(canonical, duplicate);
  }
}
const local = path.join(scope, 'dsh-base/node_modules/@deepseek-ai/dsh-sandbox-local');
if (!fs.existsSync(local)) throw Error('Stock local sandbox package missing');
const link = path.join(root, 'dsh-sandbox-local');
if (!fs.existsSync(link)) fs.symlinkSync(local, link);
