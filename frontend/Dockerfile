# frontend/Dockerfile
# 第一阶段：构建 Vue3 静态文件
FROM node:18-alpine as build-stage
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# 第二阶段：用 Nginx 运行
FROM nginx:alpine
# 将打包好的静态文件复制到 Nginx 目录
COPY --from=build-stage /app/dist /usr/share/nginx/html
# 复制自定义的 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]