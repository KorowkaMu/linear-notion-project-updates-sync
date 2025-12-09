# Linear to Notion Sync

Automate posting Linear Project Updates to Notion pages via webhooks.

## Overview

This project syncs Linear Project Updates to Notion pages using webhooks. When a project update is created in Linear, it automatically creates or updates a daily Notion document with the format: `{{team}}. Update @.{{YYYY-MM-DD}}`. Each update is added as a separate block with the project name as a heading.

## Setup

1. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```

4. Configure your credentials in `.env`:
   - `LINEAR_API_KEY`: Your Linear API key (needed to fetch team names)
   - `NOTION_API_KEY`: Your Notion integration token
   - `NOTION_DATABASE_ID`: The Notion database ID where Master Project Updates should be posted
   - `NOTION_ALL_UPDATES_DATABASE_ID`: The Notion database ID for "All project updates" (where individual updates are collected)

5. **Configure Notion Integration Database Access**:
   
   Your Notion integration needs access to both databases. To configure this:
   
   - Open your Notion workspace settings
   - Go to **Connections**
   - Click **"Develop or manage integrations"** (or go directly to [https://www.notion.so/profile/integrations](https://www.notion.so/profile/integrations))
   - Find your integration in the list
   - Click **"Edit settings"**
   - Select the **"Access"** tab
   - Click **"Edit access"** link
   - Select your team space
   - Check the databases that need to be shared:
     - The database specified in `NOTION_DATABASE_ID` (for Master Project Updates)
     - The database specified in `NOTION_ALL_UPDATES_DATABASE_ID` (for All project updates)
   - Click **"Save"**
   
   ⚠️ **Important**: Both databases must be explicitly granted access in the integration settings. Simply sharing the database with your user account is not sufficient.

## Local Testing with ngrok

To test the webhook locally before deploying:

1. **Get an ngrok auth token** (optional but recommended):
   - Sign up at [ngrok.com](https://ngrok.com)
   - Get your auth token from the dashboard
   - Add it to `.env` as `NGROK_AUTH_TOKEN`

2. **Enable ngrok in `.env`**:
   ```env
   USE_NGROK=true
   NGROK_AUTH_TOKEN=your_ngrok_auth_token_here
   ```

3. **Start the server**:
   ```bash
   source venv/bin/activate  # If not already activated
   python app.py
   ```

4. **Copy the ngrok URL** that appears in the console output. It will look like:
   ```
   🚀 ngrok tunnel established!
   Public URL: https://abc123.ngrok.io
   Webhook endpoint: https://abc123.ngrok.io/webhook
   ```

5. **Configure Linear webhook**:
   - Go to Linear Settings → API → Webhooks
   - Click "New Webhook"
   - Paste the webhook URL: `https://abc123.ngrok.io/webhook`
   - Select event type: **ProjectUpdate**
   - Save the webhook

6. **Test it**: Create a project update in Linear and watch it appear in your Notion database!

## Usage

### Local Development (with ngrok)
```bash
source venv/bin/activate
python app.py
```

The app will automatically start ngrok if `USE_NGROK=true` is set in your `.env` file.

### Production Deployment

For production, deploy to a hosting service (Heroku, Railway, Render, etc.) and:
- Set `USE_NGROK=false` (or remove it)
- Use the production URL in your Linear webhook settings
- Consider using a proper WSGI server like gunicorn

## Configuration

### Required Environment Variables

- `LINEAR_API_KEY`: Your Linear API key (for fetching team information)
- `NOTION_API_KEY`: Your Notion integration token
- `NOTION_DATABASE_ID`: The Notion database ID where Master Project Updates should be posted
- `NOTION_ALL_UPDATES_DATABASE_ID`: The Notion database ID for "All project updates" (where individual updates are collected before being aggregated into Master Updates)

### Optional Environment Variables

- `USE_NGROK`: Set to `true` to enable ngrok for local testing (default: `false`)
- `NGROK_AUTH_TOKEN`: Your ngrok auth token (recommended for authenticated sessions)
- `PORT`: Port to run the server on (default: `8000`)
- `LINEAR_WEBHOOK_SECRET`: **Required for security** - Your Linear webhook signing secret. The app will verify all incoming webhooks using HMAC-SHA256 signature verification to ensure they're authentic and prevent replay attacks.

## How It Works

1. **Webhook Reception**: The app listens for Linear webhook events at `/webhook`
2. **Document Creation**: When a ProjectUpdate event is received, it creates or finds a Notion document named: `{{team}}. Update @.{{YYYY-MM-DD}}`
3. **Block Addition**: Each project update is added as:
   - A heading (H2) with the project name
   - A paragraph with the update body

## Features

- ✅ Webhook-based syncing (real-time updates)
- ✅ Automatic daily document creation
- ✅ Team-based document organization
- ✅ Project updates as separate blocks
- ✅ Local testing support with ngrok
- ✅ Health check endpoint at `/health`

## Troubleshooting

- **ngrok not working**: Make sure `pyngrok` is installed: `pip install pyngrok`
- **Webhook not receiving events**: Check that the URL in Linear matches your ngrok URL
- **Notion database access errors (404)**: 
  - Verify your database IDs are correct in `.env`
  - Make sure both databases are granted access in your Notion integration settings (see step 5 in Setup)
  - Database IDs should be 32 characters (without dashes) - they're automatically formatted
  - You can test database access using: `GET http://localhost:8000/test-database/YOUR_DATABASE_ID`
- **Notion errors**: Verify your `NOTION_API_KEY` and database IDs are correct, and that your Notion integration has access to both databases
