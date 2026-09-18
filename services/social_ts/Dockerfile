FROM node:22.19.0-bookworm-slim AS builder

WORKDIR /app

COPY services/social_ts/package.json ./
COPY services/social_ts/prisma ./prisma

RUN npm install

COPY services/social_ts/tsconfig.json ./
COPY services/social_ts/src ./src

RUN npx prisma generate && npm run build

# Runtime does not need TypeScript, tsx, or the Prisma CLI. Keep the generated
# Prisma client/engine and production dependencies only before copying
# node_modules into the final image.
RUN npm prune --omit=dev && npm cache clean --force


FROM node:22.19.0-bookworm-slim

ENV NODE_ENV=production

WORKDIR /app

COPY services/social_ts/package.json ./
COPY services/social_ts/prisma ./prisma
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist

USER node

EXPOSE 8080

CMD ["node", "dist/server.js"]
