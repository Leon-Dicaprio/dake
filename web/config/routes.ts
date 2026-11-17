/** 事件、单次运行和持续处理各自保留明确入口，刷新后从后端恢复状态。 */
export default [
  {
    path: '/',
    component: '@/layouts/Workspace',
    routes: [
      { path: '/', redirect: '/events' },
      { path: '/events', component: './events' },
      { path: '/runs', component: './runs' },
      { path: '/schedules', component: './schedules' },
      { path: '*', component: './not-found' },
    ],
  },
];
