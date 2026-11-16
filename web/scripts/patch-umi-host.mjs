import { readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve, sep } from 'node:path';

/**
 * Umi 4.7.3 的开发服务器把 HOST 用于提示文字，却未传给 listen。
 * 安装和启动时只修复本工程这一版本的一处调用，确保按 HOST 监听；缺省仅本机。
 * 升级或上游实现改变后直接终止，重新核对后才能继续启动。
 */
const require = createRequire(import.meta.url);
const webRoot = realpathSync(resolve(import.meta.dirname, '..'));
const packagePath = require.resolve('@umijs/bundler-webpack/package.json');
const packageRoot = realpathSync(dirname(packagePath));
if (!packageRoot.startsWith(`${webRoot}${sep}node_modules${sep}`)) {
  throw new Error('只允许修复当前 web 工程内的 Umi 依赖。');
}
const metadata = JSON.parse(readFileSync(packagePath, 'utf8'));
if (metadata.version !== '4.7.3') {
  throw new Error(
    `Umi 构建依赖已变为 ${metadata.version}，请重新核对本地监听方式。`,
  );
}
const target = resolve(packageRoot, 'dist/server/server.js');
const source = readFileSync(target, 'utf8');
const original = '  server.listen(port, () => {';
const corrected = '  server.listen(port, opts.host, () => {';
const originalCount = source.split(original).length - 1;
const correctedCount = source.split(corrected).length - 1;
if (originalCount === 1 && correctedCount === 0) {
  writeFileSync(target, source.replace(original, corrected));
} else if (!(originalCount === 0 && correctedCount === 1)) {
  throw new Error('Umi 开发服务器代码与预期不符，未进行修改。');
}
