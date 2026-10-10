FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci --prefer-offline --no-audit

COPY . .
RUN npm run build

FROM node:20-alpine

WORKDIR /app
COPY --from=build /app/dist ./dist
COPY package*.json ./
RUN npm install -g preview

EXPOSE 3000

CMD ["npx", "vite", "preview", "--host", "0.0.0.0", "--port", "3000"]
