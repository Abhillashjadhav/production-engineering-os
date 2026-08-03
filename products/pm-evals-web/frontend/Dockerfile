# Build the React/Vite SPA with the exact lockfile, then serve only static
# artifacts from a stable nginx runtime with no application build framework.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.28-alpine
ENV BACKEND_URL=http://backend:8000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
RUN test -f /usr/share/nginx/html/BUILD_ID
EXPOSE 3000
HEALTHCHECK --interval=5s --timeout=3s --retries=12 \
  CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
