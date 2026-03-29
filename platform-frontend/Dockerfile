# Use a simple static file server for correct MIME types in Azure/Node.js
# This Dockerfile assumes you have a Vite build output in /dist
FROM node:20-alpine as build
WORKDIR /app
COPY . .
RUN npm ci && npm run build

FROM node:20-alpine as prod
WORKDIR /app
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./
# Install only serve (or http-server) for static hosting
RUN npm install --omit=dev --no-save serve
EXPOSE 4173
CMD ["npx", "serve", "-s", "dist", "-l", "4173"]
