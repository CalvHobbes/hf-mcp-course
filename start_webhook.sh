#!/bin/bash

# Start the webhook server in the background, redirect stderr to a log file
python3 webhook_server.py 2>webhook_error.log &
WEBHOOK_PID=$!
sleep 2

# Check if the webhook server is still running
if ! kill -0 $WEBHOOK_PID 2>/dev/null; then
    echo "Error: Failed to start webhook_server.py. See webhook_error.log for details."
    exit 1
fi

echo "Webhook server started with PID $WEBHOOK_PID"

# Start Cloudflare tunnel to expose localhost:8080
# Replace 'your-tunnel-token' with your actual Cloudflare tunnel token if needed
# If using cloudflared without a token, this will open a temporary tunnel
cloudflared tunnel --url http://localhost:8080

# Optional: Kill the webhook server when done (uncomment if desired)
# kill $WEBHOOK_PID 