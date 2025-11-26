# Testing Guide

Follow these steps to test the Linear to Notion webhook integration locally.

## Prerequisites

Before you start, make sure you have:
- ✅ Virtual environment activated
- ✅ Dependencies installed (`pip install -r requirements.txt`)
- ✅ Linear account with API access
- ✅ Notion workspace with API access

## Step 1: Get Your API Keys and IDs

### A. Linear API Key
1. Go to [Linear Settings → API](https://linear.app/settings/api)
2. Under "Personal API keys", click "Create API key"
3. Give it a name (e.g., "Notion Sync")
4. Copy the API key (you'll only see it once!)

### B. Notion Integration Token
1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click "+ New integration"
3. Give it a name (e.g., "Linear Sync")
4. Select your workspace
5. Under "Capabilities", enable:
   - ✅ Read content
   - ✅ Insert content
   - ✅ Update content
6. Click "Submit" and copy the "Internal Integration Token"

### C. Notion Database ID
1. Open your Notion database in a browser
2. Look at the URL: `https://www.notion.so/workspace/DATABASE_ID?v=...`
3. The Database ID is the long string between the workspace name and `?v=`
4. Remove any hyphens from the ID (Notion uses a 32-character hex string)
   - Example: If URL has `a1b2c3d4-e5f6-...`, the ID is `a1b2c3d4e5f6...` (32 chars)

### D. ngrok Auth Token (Optional but Recommended)
1. Sign up at [ngrok.com](https://ngrok.com) (free account works)
2. Go to [ngrok Dashboard → Your Authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
3. Copy your authtoken

## Step 2: Create Your .env File

Create a `.env` file in the project root:

```bash
touch .env
```

Add the following content (replace with your actual values):

```env
# Linear API Configuration
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Notion API Configuration
NOTION_API_KEY=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_DATABASE_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Linear Webhook Secret (get this when creating the webhook in Step 4)
LINEAR_WEBHOOK_SECRET=

# ngrok Configuration (for local testing)
USE_NGROK=true
NGROK_AUTH_TOKEN=your_ngrok_auth_token_here
PORT=8000
```

**Important**: 
- Don't commit the `.env` file to git (it should be in `.gitignore`)
- Replace all placeholder values with your actual credentials

## Step 3: Share Notion Database with Integration

1. Open your Notion database
2. Click the "..." menu in the top right
3. Click "Connections" → "Add connections"
4. Search for and select your integration (the one you created in Step 1B)
5. Click "Confirm"

## Step 4: Start the App

1. Make sure your virtual environment is activated:
   ```bash
   source venv/bin/activate
   ```

2. Start the app:
   ```bash
   python app.py
   ```

3. You should see output like:
   ```
   ============================================================
   🚀 ngrok tunnel established!
   ============================================================
   Public URL: https://abc123.ngrok-free.dev
   Webhook endpoint: https://abc123.ngrok-free.dev/webhook
   Health check: https://abc123.ngrok-free.dev/health
   
   ⚠️  Copy the webhook URL above and use it in Linear webhook settings
   ============================================================
   ```

4. **Copy the webhook endpoint URL** (e.g., `https://abc123.ngrok-free.dev/webhook`)

## Step 5: Create Linear Webhook

1. Go to [Linear Settings → API → Webhooks](https://linear.app/settings/api/webhooks)
2. Click "New webhook"
3. Fill in the form:
   - **Label**: Give it a name (e.g., "Notion Sync")
   - **URL**: Paste the webhook endpoint from Step 4 (e.g., `https://abc123.ngrok-free.dev/webhook`)
   - **Events**: Select "Project update" (or "ProjectUpdate")
4. Click "Create webhook"
5. **Important**: Copy the "Signing secret" that appears
6. Add the signing secret to your `.env` file:
   ```env
   LINEAR_WEBHOOK_SECRET=your_signing_secret_here
   ```
7. **Restart the app** (Ctrl+C to stop, then `python app.py` again) to load the webhook secret
   
   **Note**: The app will work without the secret (with a warning), but you should add it and restart for proper security. After the initial setup, you won't need to restart again unless you change the secret.

## Step 6: Test the Webhook

1. **Keep the app running** (the terminal should show the Flask server running)

2. **Create a test project update in Linear**:
   - Go to a project in Linear
   - Click on the project
   - Add a project update (look for "Project update" or similar)
   - Write some test content
   - Save the update

3. **Check the app console** - You should see:
   ```
   Processing update for project: Your Project Name, team: Your Team Name
   ✓ Successfully added update to Notion document
   ```

4. **Check your Notion database**:
   - Open your Notion database
   - You should see a new document (or an existing one updated) with the format:
     - Title: `{{Team Name}}. Update @.{{YYYY-MM-DD}}`
     - Content: A heading with the project name, followed by the update content

## Troubleshooting

### App won't start
- Check that all environment variables are set in `.env`
- Make sure port 8000 is not in use: `lsof -i :8000`
- Try a different port by setting `PORT=8001` in `.env`

### ngrok not working
- Make sure `USE_NGROK=true` in `.env`
- Verify `NGROK_AUTH_TOKEN` is set (optional but recommended)
- Check that pyngrok is installed: `pip install pyngrok`

### Webhook not receiving events
- Verify the webhook URL in Linear matches your ngrok URL
- Check that the app is still running
- Look for errors in the app console
- Test the health endpoint: Open `https://your-ngrok-url.ngrok-free.dev/health` in a browser

### Signature verification failing
- Make sure `LINEAR_WEBHOOK_SECRET` is set in `.env`
- Verify the secret matches what Linear shows in the webhook settings
- Restart the app after adding the secret

### Notion errors
- Verify `NOTION_API_KEY` is correct
- Check that `NOTION_DATABASE_ID` is correct (32 characters, no hyphens)
- Ensure the integration has access to the database (Step 3)
- Check that the database has a "Name" property (title type)

### No updates appearing in Notion
- Check the app console for error messages
- Verify the project update was actually created in Linear
- Make sure the webhook event type is "ProjectUpdate" in Linear settings
- Check that the team name is being fetched correctly (requires `LINEAR_API_KEY`)

## Next Steps

Once testing is successful:
- The app is ready for production deployment
- Consider using a proper WSGI server (like gunicorn) for production
- Set up monitoring and logging for production use
- Remove `USE_NGROK=true` when deploying to a production server

