/** 仅开发时代理到本地 Python 服务，生产部署由同源反向代理接管。 */
const target = process.env.DAKE_API_PROXY || 'http://127.0.0.1:8001';
export default {
  '/api/': { target, changeOrigin: false },
  '/health': { target, changeOrigin: false },
};
