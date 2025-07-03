import axios from 'axios';

const backendPort = import.meta.env.VITE_BACKEND_PORT;
// 动态获取当前浏览器地址栏的 IP 或域名
const currentHost = `${window.location.protocol}//${window.location.hostname}:${backendPort}/api`;

const instance = axios.create({
  baseURL: currentHost,
  timeout: 1000,
  headers: { 'Content-Type': 'application/json' },
});

export default instance;
