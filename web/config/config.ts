import { defineConfig } from 'umi';
import proxy from './proxy';
import routes from './routes';

/** 前端只访问同源接口；本地代理连接独立的 Python 服务。 */
export default defineConfig({
  title: '大客售后',
  hash: true,
  publicPath: '/',
  outputPath: process.env.NODE_ENV === 'development' ? '.output/dev' : 'dist',
  mfsu: false,
  mock: false,
  fastRefresh: true,
  esbuildMinifyIIFE: true,
  routes,
  proxy,
  metas: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
  chainWebpack(memo) {
    memo.module
      .rule('tailwind')
      .enforce('pre')
      .test(/[/\\]tailwind\.css$/)
      .use('tailwind')
      .loader(require.resolve('@tailwindcss/webpack'));
    return memo;
  },
});
