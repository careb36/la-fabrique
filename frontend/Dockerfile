FROM node:26-alpine

WORKDIR /app

# Disable Electron download during build
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1

# The unprivileged `node` user (uid 1000) owns the app: npm and Vite write
# their caches under node_modules at run time.
RUN chown node:node /app
USER node

COPY --chown=node:node package*.json ./
RUN npm ci

COPY --chown=node:node . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
