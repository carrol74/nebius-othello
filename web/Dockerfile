FROM node:22-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
COPY web/package.json web/
RUN npm ci
COPY web web
RUN npm run build

FROM node:22-slim

ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app /app
WORKDIR /app/web
USER node
EXPOSE 3000
CMD ["/app/node_modules/.bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
