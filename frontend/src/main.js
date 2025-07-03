import { createApp } from 'vue';
import ElementPlus from 'element-plus';
import * as ElIcons from '@element-plus/icons-vue';
import 'element-plus/dist/index.css';
import App from './App.vue';
import router from './router';
import { createPinia } from 'pinia';
var pinia = createPinia();
var app = createApp(App);
// Register all icons
for (var _i = 0, _a = Object.entries(ElIcons); _i < _a.length; _i++) {
    var _b = _a[_i], key = _b[0], component = _b[1];
    app.component(key, component);
}
app.use(pinia);
app.use(router);
app.use(ElementPlus);
app.mount('#app');
