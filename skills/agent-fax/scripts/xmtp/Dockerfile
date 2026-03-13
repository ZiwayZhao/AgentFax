FROM node:22-slim

# XMTP SDK uses gRPC over TLS — need CA certificates in slim image
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /bridge

COPY package.json ./
RUN npm install --production && npm cache clean --force

COPY xmtp_bridge.js ./

# Bridge listens on this port inside the container
EXPOSE 3500

CMD ["node", "xmtp_bridge.js"]
