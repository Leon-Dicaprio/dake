import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { generateService } from '@umijs/openapi';

const require = createRequire(import.meta.url);
const schemaPath = resolve(import.meta.dirname, '../docs/api/openapi.json');

/** OpenAPI 3.1 的可空类型数组转为生成器认识的 anyOf，仅调整内存中的契约。 */
function normalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalize);
  if (!value || typeof value !== 'object') return value;
  const schema = Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, normalize(item)]),
  );
  if (!Array.isArray(schema.type)) return schema;
  const { type, ...fields } = schema;
  return {
    ...fields,
    anyOf: type.map((member) => ({ ...fields, type: member })),
  };
}

// 使用后端导出的唯一契约；生成物不手工维护。
require.cache[schemaPath] = {
  id: schemaPath,
  filename: schemaPath,
  loaded: true,
  exports: normalize(JSON.parse(readFileSync(schemaPath, 'utf8'))),
} as NodeJS.Module;
await generateService({
  schemaPath,
  serversPath: resolve(import.meta.dirname, 'src/services'),
  projectName: 'generated',
  requestLibPath: "import { request } from '@/services/request'",
  requestOptionsType: '{ signal?: AbortSignal }',
  isCamelCase: true,
});
