FROM node:24-alpine AS build
WORKDIR /src
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build
FROM nginx:stable-alpine
COPY --from=build /src/dist /usr/share/nginx/html
