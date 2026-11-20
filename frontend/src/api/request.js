import axios from 'axios'

// 生产环境走 nginx 反代 /api -> backend:8000。
// 原来写死 http://127.0.0.1:8000 会导致线上用户的浏览器去请求自己电脑的 8000 端口，接口全挂。
// 本地开发时 vite.config.js 里同样配置了 /api 代理到 http://127.0.0.1:8000。
const request = axios.create({
    baseURL: import.meta.env.VITE_API_BASE || '/api',
    // 大模型对话属长耗时请求，5 秒必然超时
    timeout: 120000
})

export default request
