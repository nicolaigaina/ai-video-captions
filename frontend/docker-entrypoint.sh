#!/bin/sh
set -e

# Run Prisma migrations/push on startup
npx --yes prisma@6.19.2 db push --accept-data-loss --skip-generate

# Start the Next.js server
exec node server.js
