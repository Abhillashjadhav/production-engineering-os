# pm-evals Web frontend: production build served by `next start`.
# The /api rewrite target is BAKED AT BUILD TIME (next.config.mjs rewrites are
# evaluated during `next build`), so BACKEND_URL is a build argument — the
# compose file points it at the backend service.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
RUN npx next build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/next.config.mjs ./
COPY --from=build /app/.next ./.next
EXPOSE 3000
CMD ["npx", "next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
