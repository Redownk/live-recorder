import { createRouter, createWebHistory } from 'vue-router';

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/rooms' },
    { path: '/rooms', component: () => import('./views/RoomsView.vue'), meta: { title: '直播间' } },
    { path: '/logs', component: () => import('./views/LogsView.vue'), meta: { title: '录制日志' } },
    { path: '/runtime-logs', component: () => import('./views/RuntimeLogsView.vue'), meta: { title: '运行日志' } },
    { path: '/diagnostics', component: () => import('./views/DiagnosticsView.vue'), meta: { title: '故障诊断' } },
    { path: '/videos', component: () => import('./views/VideosView.vue'), meta: { title: '视频文件' } },
    { path: '/processing', redirect: '/processing/transcode' },
    { path: '/processing/:mode(transcode|merge)', component: () => import('./views/ProcessingView.vue'), meta: { title: '视频处理' } },
    { path: '/settings', component: () => import('./views/SettingsView.vue'), meta: { title: '设置' } },
    { path: '/:pathMatch(.*)*', redirect: '/rooms' },
  ],
  scrollBehavior: () => ({ top: 0 }),
});
