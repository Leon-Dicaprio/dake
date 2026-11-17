/** 只保留事件和处理记录两个业务入口，刷新详情时仍由同一页面恢复。 */
export default [
  {
    path: '/',
    component: '@/layouts/Workspace',
    routes: [
      { path: '/', redirect: '/events' },
      { path: '/events', component: './events' },
      { path: '/runs', component: './runs' },
      { path: '*', component: './not-found' },
    ],
  },
];
