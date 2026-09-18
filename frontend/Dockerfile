FROM node:20.19.4-alpine3.22 AS build

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.30.4-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY docker-entrypoint.d/40-mreader-runtime-config.sh /docker-entrypoint.d/40-mreader-runtime-config.sh
RUN chmod +x /docker-entrypoint.d/40-mreader-runtime-config.sh
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
