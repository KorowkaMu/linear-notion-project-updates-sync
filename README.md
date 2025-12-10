# Linear to Notion Sync

Automate posting Linear Project Updates to Notion pages via webhooks.

## Overview

This project syncs Linear Project Updates to Notion pages using webhooks. When a project update is created in Linear, it automatically creates or updates a a record in the "All project updates" db in Notion. There is also a scheduler that runs every 2 hours Friday - Monday, fetchesh all the updates for the week from "All project updates" db, assembles them into a single "Project Updates" doc and post to Company Updates Database.

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

The project is ready for deployment to hosting services like Heroku, Railway, Render, Fly.io, etc.

#### Quick Deploy Steps:

1. **Push your code to GitHub** (if not already done)

2. **Choose a hosting platform** and connect your repository:
   - **Heroku**: Create a new app, connect GitHub repo, deploy
   - **Railway**: New project → Deploy from GitHub repo
   - **Render**: New Web Service → Connect GitHub repo
   - **Fly.io**: `fly launch` (requires Fly CLI)

3. **Set environment variables** in your hosting platform's dashboard:
   ```
   LINEAR_API_KEY=your_key
   LINEAR_WEBHOOK_SECRET=your_secret
   NOTION_API_KEY=your_token
   NOTION_DATABASE_ID=your_database_id
   NOTION_ALL_UPDATES_DATABASE_ID=your_all_updates_database_id
   OPENAI_API_KEY=your_key (optional)
   OPENAI_MODEL=gpt-4o-mini (optional)
   USE_NGROK=false
   ```

4. **Update Linear webhook URL**:
   - Go to Linear Settings → API → Webhooks
   - Update your webhook URL to: `https://your-app-url.com/webhook`

5. **Deploy!** The platform will automatically:
   - Install dependencies from `requirements.txt`
   - Use `Procfile` to start the app with gunicorn
   - Set the `PORT` environment variable automatically

#### Files Included for Deployment:
- ✅ `Procfile` - Tells the platform how to run your app
- ✅ `requirements.txt` - Lists all Python dependencies (including gunicorn)
- ✅ `runtime.txt` - Specifies Python version (3.12)
- ✅ `.gitignore` - Ensures `.env` is not committed

#### Notes:
- The app automatically reads `PORT` from environment (hosting platforms set this)
- `USE_NGROK` should be `false` or unset in production
- Gunicorn will handle the WSGI server (configured in Procfile)
- The cron job scheduler runs in a background thread automatically

## Cron Scheduler Configuration

The app includes a built-in cron scheduler that automatically generates Master Project Updates every 2 hours during Friday-Monday (UTC).

### How It Works

- **Schedule**: Runs every 2 hours, but only executes on Friday, Saturday, Sunday, and Monday (UTC)
- **Implementation**: Uses the `schedule` library running in a background daemon thread
- **Automatic**: No additional configuration needed - it starts automatically when the app runs
- **Retry Logic**: Includes 5 retries with exponential backoff if the Master Update generation fails

### Important Notes

1. **Single Worker Required**: The `Procfile` is configured with `--workers 1` to ensure only one cron scheduler instance runs. If you need multiple workers for higher webhook throughput, consider using platform-specific cron jobs instead (see below).

2. **UTC Timezone**: The scheduler uses UTC time to determine if it's Friday-Monday. Make sure your hosting platform's timezone is set correctly.

3. **Manual Trigger**: You can manually trigger a Master Update by sending a POST request to `/generate-master-update` endpoint.

### Alternative: Platform-Specific Cron Jobs

If you need multiple gunicorn workers for better performance, you can disable the built-in scheduler and use your hosting platform's cron system instead:

#### Option 1: Keep Built-in Scheduler (Current Setup)
- ✅ Already configured, no additional setup needed
- ✅ Works automatically
- ⚠️ Requires single worker (good for low-medium traffic)

#### Option 2: Use Platform Cron Jobs
If your hosting platform supports scheduled tasks (Heroku Scheduler, Railway Cron, Render Cron Jobs, etc.):

1. **Disable built-in scheduler** (optional - you can keep both):
   - The built-in scheduler will still work, but you can rely on platform cron instead

2. **Set up platform cron job**:
   - **Schedule**: Every 2 hours, Friday-Monday (UTC)
   - **Command**: `curl -X POST https://your-app-url.com/generate-master-update`
   - **Or use a worker process**: Some platforms allow you to run a separate worker that calls the endpoint

3. **Example Platform Configurations**:

   **Heroku Scheduler** (add-on):
   - Install the Heroku Scheduler add-on
   - Add a job with:
     - **Schedule**: Every 2 hours (you'll need to add multiple jobs for Fri, Sat, Sun, Mon)
     - **Command**: `curl -X POST https://your-app.herokuapp.com/generate-master-update`
   - Note: Heroku Scheduler runs at specific times, so you may need to create separate jobs for each 2-hour interval on Fri-Mon

   **Railway Cron**:
   - Railway doesn't have built-in cron, but you can use a separate worker process
   - Or use Railway's scheduled tasks feature if available
   - Command: `curl -X POST https://your-app.railway.app/generate-master-update`

   **Render Cron Job**:
   - Go to your service → Cron Jobs → New Cron Job
   - **Schedule**: Custom cron expression (check Render docs for exact syntax)
   - **Command**: `curl -X POST https://your-app.onrender.com/generate-master-update`

   **Note**: Platform cron syntax varies. Check your platform's documentation for the exact format. The built-in scheduler is usually simpler and works out of the box.

### Verifying Cron Scheduler

Check your app logs to confirm the cron scheduler started:
```
🕐 Cron job scheduler started (runs every 2 hours, Friday-Monday only)
✅ Cron job thread started
```

When the cron job runs, you'll see:
```
⏰ Cron job triggered (Friday-Monday)
```

If it's not the right day:
```
⏰ Cron job skipped (not Friday-Monday, current day: Tuesday)
```

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
