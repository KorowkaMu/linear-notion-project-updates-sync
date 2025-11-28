"""
Linear to Notion Sync
Automates posting Linear Project Updates to Notion pages via webhooks. Also updates the Contact property with the author of the update.
"""

import os
import hmac
import hashlib
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# Optional ngrok import for local testing
try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configuration
LINEAR_API_KEY = os.getenv('LINEAR_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
LINEAR_WEBHOOK_SECRET = os.getenv('LINEAR_WEBHOOK_SECRET', '')
USE_NGROK = os.getenv('USE_NGROK', 'false').lower() == 'true'
NGROK_AUTH_TOKEN = os.getenv('NGROK_AUTH_TOKEN', '')

# API endpoints
LINEAR_API_URL = 'https://api.linear.app/graphql'
NOTION_API_URL = 'https://api.notion.com/v1'

# Flask app
app = Flask(__name__)


def get_team_name(team_id):
    """
    Fetch team name from Linear using GraphQL API.
    """
    if not LINEAR_API_KEY:
        return "Unknown Team"
    
    headers = {
        'Authorization': LINEAR_API_KEY,
        'Content-Type': 'application/json',
    }
    
    query = """
    query($id: String!) {
      team(id: $id) {
        name
      }
    }
    """
    
    try:
        response = requests.post(
            LINEAR_API_URL,
            json={'query': query, 'variables': {'id': team_id}},
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            team = data.get('data', {}).get('team', {})
            return team.get('name', 'Unknown Team')
    except Exception as e:
        print(f"Error fetching team name: {e}")
    
    return "Unknown Team"


def find_notion_user_by_name(contact_name, headers):
    """
    Search for a Notion user by name or email.
    Returns the user ID if found, None otherwise.
    """
    try:
        # Search users endpoint
        search_url = f'{NOTION_API_URL}/users'
        print(f"      Searching Notion users...")
        
        response = requests.get(search_url, headers=headers)
        
        if response.status_code == 200:
            users = response.json().get('results', [])
            print(f"      Found {len(users)} users in workspace")
            
            # Try to match by name or email
            contact_name_lower = contact_name.lower()
            for user in users:
                user_name = user.get('name', '')
                user_email = ''
                
                # Get email if available (might be in person object)
                person = user.get('person', {})
                if person:
                    user_email = person.get('email', '')
                
                # Match by name or email
                if (user_name and contact_name_lower in user_name.lower()) or \
                   (user_email and contact_name_lower in user_email.lower()):
                    user_id = user.get('id')
                    print(f"      ✅ Matched user: {user_name or user_email} (ID: {user_id})")
                    return user_id
            
            print(f"      ⚠️  No matching user found for: {contact_name}")
            return None
        else:
            print(f"      ⚠️  Error searching users: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"      ❌ Exception searching users: {e}")
        return None


def update_contact_property(page_id, contact_name):
    """
    Update the Contact property of a Notion page to include the new contact.
    If the contact already exists, it won't be duplicated.
    """
    if not NOTION_API_KEY:
        print("   ❌ Error: NOTION_API_KEY not set")
        return False
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        # First, get the current page to read the existing Contact property
        print(f"   📖 Reading current page properties...")
        get_page_response = requests.get(
            f'{NOTION_API_URL}/pages/{page_id}',
            headers=headers
        )
        
        if get_page_response.status_code != 200:
            print(f"   ⚠️  Could not read page: {get_page_response.status_code}")
            print(f"   Response: {get_page_response.text}")
            return False
        
        page_data = get_page_response.json()
        properties = page_data.get('properties', {})
        contact_property = properties.get('Contact', {})
        
        # Get existing contacts
        existing_contacts = []
        existing_user_ids = []  # For people property type
        contact_type = contact_property.get('type')
        
        if contact_type == 'rich_text':
            # Rich text property - extract text content
            rich_text = contact_property.get('rich_text', [])
            existing_contacts = [item.get('plain_text', '').strip() for item in rich_text if item.get('plain_text')]
        elif contact_type == 'title':
            # Title property
            title = contact_property.get('title', [])
            existing_contacts = [item.get('plain_text', '').strip() for item in title if item.get('plain_text')]
        elif contact_type == 'multi_select':
            # Multi-select property
            multi_select = contact_property.get('multi_select', [])
            existing_contacts = [item.get('name', '').strip() for item in multi_select if item.get('name')]
        elif contact_type == 'people':
            # People property - extract user objects
            people = contact_property.get('people', [])
            existing_user_ids = [person.get('id') for person in people if person.get('id')]
            # Also get names for logging
            existing_contacts = []
            for person in people:
                name = person.get('name') or person.get('person', {}).get('name') or person.get('person', {}).get('email', '')
                if name:
                    existing_contacts.append(name)
        
        # Remove empty strings and duplicates
        existing_contacts = list(set([c for c in existing_contacts if c]))
        
        print(f"   Existing contacts: {existing_contacts}")
        if contact_type == 'people':
            print(f"   Existing user IDs: {existing_user_ids}")
        
        # For people property, we need to find the user ID
        new_user_id = None
        if contact_type == 'people' and contact_name:
            # Try to find the user in Notion by searching users
            print(f"   🔍 Searching for user: {contact_name}")
            new_user_id = find_notion_user_by_name(contact_name, headers)
            if new_user_id:
                if new_user_id not in existing_user_ids:
                    existing_user_ids.append(new_user_id)
                    print(f"   ✅ Found user and adding: {contact_name} (ID: {new_user_id})")
                else:
                    print(f"   ℹ️  User already exists in Contact property")
            else:
                print(f"   ⚠️  Could not find user '{contact_name}' in Notion workspace")
                print(f"   💡 The Contact property will not be updated for this user")
                return False  # Skip update if we can't find the user
        elif contact_name and contact_name not in existing_contacts:
            existing_contacts.append(contact_name)
            print(f"   Adding new contact: {contact_name}")
        elif contact_name in existing_contacts:
            print(f"   Contact already exists: {contact_name}")
        
        # Update the Contact property
        # Try different property types
        contact_value = None
        
        if contact_type == 'rich_text' or contact_type is None:
            # Default to rich_text if type is unknown
            # Join all contacts with ", " separator
            contacts_text = ', '.join(existing_contacts)
            contact_value = {
                'rich_text': [
                    {'text': {'content': contacts_text}}
                ]
            }
        elif contact_type == 'title':
            # Title property - join contacts with separator
            contact_value = {
                'title': [
                    {'text': {'content': ', '.join(existing_contacts)}}
                ]
            }
        elif contact_type == 'multi_select':
            contact_value = {
                'multi_select': [
                    {'name': contact} for contact in existing_contacts
                ]
            }
        elif contact_type == 'people':
            # People property - need user objects with IDs
            contact_value = {
                'people': [
                    {'object': 'user', 'id': user_id} for user_id in existing_user_ids
                ]
            }
            print(f"   Updating people property with {len(existing_user_ids)} user(s)")
        else:
            print(f"   ⚠️  Unknown Contact property type: {contact_type}")
            # Try rich_text as fallback - join contacts with comma
            contacts_text = ', '.join(existing_contacts)
            contact_value = {
                'rich_text': [
                    {'text': {'content': contacts_text}}
                ]
            }
        
        # Update the page
        print(f"   📝 Updating Contact property...")
        update_response = requests.patch(
            f'{NOTION_API_URL}/pages/{page_id}',
            json={'properties': {'Contact': contact_value}},
            headers=headers
        )
        
        print(f"   Update response status: {update_response.status_code}")
        
        if update_response.status_code == 200:
            print(f"   ✅ Successfully updated Contact property")
            return True
        else:
            print(f"   ❌ Error updating Contact property: {update_response.status_code}")
            print(f"   Response: {update_response.text}")
            return False
            
    except Exception as e:
        print(f"   ❌ Exception updating Contact property: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_last_friday_of_week():
    """
    Calculate the date of the last Friday of the current week.
    Returns the date as a datetime object.
    - If today is Monday-Thursday: returns the upcoming Friday (this week)
    - If today is Friday: returns today
    - If today is Saturday-Sunday: returns the previous Friday (this week)
    """
    today = datetime.now()
    # Get the day of the week (Monday=0, Sunday=6)
    days_since_monday = today.weekday()
    
    # Friday is day 4 (0=Monday, 4=Friday, 6=Sunday)
    if days_since_monday <= 4:
        # Monday through Friday: calculate days until Friday
        days_until_friday = 4 - days_since_monday
        last_friday = today + timedelta(days=days_until_friday)
    else:
        # Saturday or Sunday: go back to the previous Friday
        days_since_friday = days_since_monday - 4
        last_friday = today - timedelta(days=days_since_friday)
    
    return last_friday


def update_week_ending_property(page_id, headers):
    """
    Update the 'Week ending on' property with the last Friday of the current week.
    """
    try:
        # Calculate last Friday of the week
        last_friday = get_last_friday_of_week()
        week_ending_date = last_friday.strftime('%Y-%m-%d')
        
        print(f"   📅 Updating 'Week ending on' property to: {week_ending_date}")
        
        # Update the page property
        update_response = requests.patch(
            f'{NOTION_API_URL}/pages/{page_id}',
            json={
                'properties': {
                    'Week ending on': {
                        'date': {
                            'start': week_ending_date
                        }
                    }
                }
            },
            headers=headers
        )
        
        if update_response.status_code == 200:
            print(f"   ✅ Successfully updated 'Week ending on' property")
            return True
        else:
            print(f"   ⚠️  Could not update 'Week ending on' property: {update_response.status_code}")
            print(f"   Response: {update_response.text}")
            return False
            
    except Exception as e:
        print(f"   ⚠️  Exception updating 'Week ending on' property: {e}")
        return False


def find_or_create_notion_document(team_name, date_str, contact_name=None):
    """
    Find or create a Notion document with the format: "{{team}} Update @{{date}}"
    Returns the page ID if found or created, None otherwise.
    """
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        print("   ❌ Error: NOTION_API_KEY and NOTION_DATABASE_ID must be set")
        return None
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    document_title = f"{team_name} Update @{date_str}"
    print(f"   Searching for document: '{document_title}'")
    
    # First, try to find existing document by querying the database
    query_url = f'{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}/query'
    print(f"   Query URL: {query_url}")
    
    try:
        # Query database for existing document with matching title
        # Note: Notion's title filter uses 'contains' or we can search all and filter client-side
        print("   🔍 Querying Notion database...")
        query_response = requests.post(
            query_url,
            json={
                'filter': {
                    'property': 'Name',
                    'title': {
                        'equals': document_title
                    }
                },
                'page_size': 1
            },
            headers=headers
        )
        
        print(f"   Query response status: {query_response.status_code}")
        
        if query_response.status_code == 200:
            results = query_response.json().get('results', [])
            print(f"   Found {len(results)} matching document(s)")
            if results:
                # Document exists, return its ID
                page_id = results[0]['id']
                print(f"   ✅ Using existing document: {page_id}")
                # Update Week ending on property if needed
                update_week_ending_property(page_id, headers)
                return page_id
        else:
            print(f"   ⚠️  Query failed: {query_response.text}")
        
        # Document doesn't exist, create it
        print("   📝 Creating new Notion document...")
        
        # Calculate last Friday of the week
        last_friday = get_last_friday_of_week()
        week_ending_date = last_friday.strftime('%Y-%m-%d')
        print(f"   Week ending on (last Friday): {week_ending_date}")
        
        page_data = {
            'parent': {'database_id': NOTION_DATABASE_ID},
            'properties': {
                'Name': {
                    'title': [
                        {
                            'text': {
                                'content': document_title
                            }
                        }
                    ]
                },
                'Week ending on': {
                    'date': {
                        'start': week_ending_date
                    }
                }
            }
        }
        
        # Add Contact property if contact_name is provided
        # Note: For people property type, we'll update it after creation
        # since we need to search for the user ID first
        if contact_name:
            # We'll update the Contact property after page creation
            # to handle different property types correctly
            pass
        
        create_response = requests.post(
            f'{NOTION_API_URL}/pages',
            json=page_data,
            headers=headers
        )
        
        print(f"   Create response status: {create_response.status_code}")
        
        if create_response.status_code == 200:
            page_id = create_response.json()['id']
            print(f"   ✅ Created new document: {page_id}")
            return page_id
        else:
            print(f"   ❌ Error creating Notion document: {create_response.status_code}")
            print(f"   Response: {create_response.text}")
            return None
            
    except Exception as e:
        print(f"   ❌ Exception finding/creating Notion document: {e}")
        import traceback
        traceback.print_exc()
        return None


def add_project_update_block(page_id, project_name, update_body, project_url=None):
    """
    Add a new block to a Notion page with project name as heading and update content.
    """
    if not NOTION_API_KEY:
        print("   ❌ Error: NOTION_API_KEY not set")
        return False
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    # Create blocks: heading with project name, then paragraph with update body
    # Build heading rich text, optionally hyperlinking to the Linear project
    heading_text = {
        'type': 'text',
        'text': {
            'content': project_name
        }
    }

    if project_url:
        heading_text['text']['link'] = {'url': project_url}

    blocks = [
        {
            'object': 'block',
            'type': 'heading_2',
            'heading_2': {
                'rich_text': [
                    heading_text
                ]
            }
        },
        {
            'object': 'block',
            'type': 'paragraph',
            'paragraph': {
                'rich_text': [
                    {
                        'type': 'text',
                        'text': {
                            'content': update_body
                        }
                    }
                ]
            }
        }
    ]
    
    print(f"   Adding blocks to page {page_id}")
    print(f"   Block 1: heading_2 with '{project_name}'")
    print(f"   Block 2: paragraph with {len(update_body)} chars")
    
    try:
        patch_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
        print(f"   PATCH URL: {patch_url}")
        
        response = requests.patch(
            patch_url,
            json={'children': blocks},
            headers=headers
        )
        
        print(f"   Response status: {response.status_code}")
        
        if response.status_code == 200:
            print(f"   ✅ Successfully added blocks")
            return True
        else:
            print(f"   ❌ Error adding block to Notion page: {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"   ❌ Exception adding project update block: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_linear_signature(request):
    """
    Verify the Linear webhook signature to ensure the request is authentic.
    Returns True if signature is valid, False otherwise.
    """
    if not LINEAR_WEBHOOK_SECRET:
        # If no secret is configured, skip verification (not recommended for production)
        print("⚠️  Warning: LINEAR_WEBHOOK_SECRET not set, skipping signature verification")
        return True
    
    # Get the signature from headers
    signature = request.headers.get('Linear-Signature')
    if not signature:
        print("❌ Error: Linear-Signature header missing")
        print(f"   Available headers: {list(request.headers.keys())}")
        return False
    
    print(f"   Received signature: {signature[:20]}...")
    
    # Compute HMAC-SHA256 signature of the raw request body
    # Important: Use request.data (raw bytes) not request.get_json() which parses it
    raw_body = request.data
    print(f"   Raw body length: {len(raw_body)} bytes")
    
    computed_signature = hmac.new(
        LINEAR_WEBHOOK_SECRET.encode('utf-8'),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    
    print(f"   Computed signature: {computed_signature[:20]}...")
    
    # Use timing-safe comparison to prevent timing attacks
    is_valid = hmac.compare_digest(computed_signature, signature)
    if not is_valid:
        print("❌ Signature mismatch!")
    return is_valid


def verify_webhook_timestamp(payload):
    """
    Verify the webhook timestamp to prevent replay attacks.
    Returns True if timestamp is within acceptable range (60 seconds), False otherwise.
    """
    webhook_timestamp = payload.get('webhookTimestamp')
    if not webhook_timestamp:
        print("Warning: webhookTimestamp not found in payload")
        return True  # Allow if timestamp is missing (for backwards compatibility)
    
    # Convert milliseconds to seconds
    webhook_time = int(webhook_timestamp) / 1000
    current_time = time.time()
    
    # Check if timestamp is within the last 60 seconds
    time_diff = abs(current_time - webhook_time)
    if time_diff > 60:
        print(f"Error: Webhook timestamp is too old or too far in future. Diff: {time_diff:.2f}s")
        return False
    
    return True


def process_project_update_webhook(webhook_data):
    """
    Process a Linear webhook payload for project update events.
    Linear webhook format: { "action": "...", "data": {...}, "url": "...", "type": "..." }
    """
    try:
        print("\n🔍 Processing ProjectUpdate webhook...")
        print(f"   Full payload structure: {list(webhook_data.keys())}")
        
        # Linear webhook payload structure
        action = webhook_data.get('action')
        data = webhook_data.get('data', {})
        
        print(f"   Action: {action}")
        print(f"   Data keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
        
        # Only process create/update actions
        if action not in ['create', 'update']:
            print(f"⚠️  Ignoring action: {action}")
            return False
        
        # Extract project update information
        # Linear may send the data directly or nested under 'projectUpdate'
        project_update = data.get('projectUpdate') or data
        print(f"   Project update keys: {list(project_update.keys()) if isinstance(project_update, dict) else 'Not a dict'}")
        
        # Get project information - could be nested or referenced by ID
        project = project_update.get('project')
        print(f"   Project data: {project}")
        if not project and project_update.get('projectId'):
            # If only projectId is provided, we'd need to fetch it via API
            # For now, we'll try to get it from the data structure
            project_id = project_update.get('projectId')
            print(f"⚠️  Warning: Project data not fully included, projectId: {project_id}")
            # You may want to fetch project details via GraphQL here if needed
            project = {}
        
        project_name = project.get('name', 'Unknown Project') if project else 'Unknown Project'
        project_url = None
        if project:
            project_url = project.get('url') or project.get('webUrl')
        if not project_url:
            project_url = project_update.get('url')
        update_body = project_update.get('body', '')
        
        # Extract user/author information
        user = project_update.get('user') or project_update.get('creator') or project_update.get('author')
        contact_name = None
        if user:
            # User could be an object with name, or just a string
            if isinstance(user, dict):
                contact_name = user.get('name') or user.get('displayName') or user.get('email')
            else:
                contact_name = str(user)
        
        print(f"   Project name: {project_name}")
        print(f"   Project URL: {project_url or 'Not provided'}")
        print(f"   Update body length: {len(update_body)} chars")
        print(f"   Update body preview: {update_body[:100] if update_body else '(empty)'}...")
        print(f"   Contact/Author: {contact_name or 'Unknown'}")
        
        if not update_body:
            print("⚠️  Warning: Update body is empty")
        
        # Get team information
        team = None
        if project:
            team = project.get('team')
            if not team and project.get('teamId'):
                team_id = project.get('teamId')
                team_name = get_team_name(team_id)
            else:
                team_name = team.get('name') if team else None
        else:
            # Try to get team from projectUpdate directly
            team = project_update.get('team')
            team_name = team.get('name') if team else None
        
        # If team name is still not available, try to fetch it via API
        if not team_name:
            team_id = None
            if team:
                team_id = team.get('id')
            elif project:
                team_id = project.get('teamId')
            elif project_update.get('teamId'):
                team_id = project_update.get('teamId')
            
            if team_id:
                team_name = get_team_name(team_id)
        
        if not team_name:
            team_name = "Unknown Team"
        
        # Get current date in YYYY-MM-DD format
        date_str = datetime.now().strftime('%Y-%m-%d')
        print(f"   Date string: {date_str}")
        
        # Find or create the Notion document
        print(f"\n📄 Finding or creating Notion document...")
        print(f"   Team: {team_name}")
        print(f"   Date: {date_str}")
        print(f"   Document title will be: '{team_name} Update @{date_str}'")
        
        page_id = find_or_create_notion_document(team_name, date_str, contact_name)
        
        if not page_id:
            print("❌ Failed to find or create Notion document")
            return False
        
        print(f"✅ Notion document found/created with ID: {page_id}")
        
        # Update Contact property with the author
        if contact_name:
            print(f"\n👤 Updating Contact property with: {contact_name}")
            update_contact_property(page_id, contact_name)
        
        # Add the project update as a new block
        print(f"\n📝 Adding project update block to Notion...")
        print(f"   Project: {project_name}")
        success = add_project_update_block(page_id, project_name, update_body, project_url)
        
        if success:
            print(f"✅ Successfully added update to Notion document")
        else:
            print(f"❌ Failed to add update to Notion document")
        
        return success
        
    except Exception as e:
        print(f"Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        return False


@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """
    Handle Linear webhook requests with signature verification.
    """
    print("\n" + "="*60)
    print("📥 Webhook received at /webhook")
    print(f"   Method: {request.method}")
    print(f"   Headers: {dict(request.headers)}")
    print(f"   Content-Type: {request.content_type}")
    print(f"   Content-Length: {request.content_length}")
    print("="*60)
    
    try:
        # Verify signature BEFORE parsing JSON
        # This is critical: we need the raw request body for signature verification
        print("🔐 Verifying webhook signature...")
        signature_valid = verify_linear_signature(request)
        if not signature_valid:
            print("❌ Webhook signature verification failed")
            abort(401, 'Invalid signature')
        print("✅ Signature verification passed")
        
        # Now parse the JSON payload
        print("📄 Parsing JSON payload...")
        payload = request.get_json()
        
        if not payload:
            print("❌ Invalid or empty payload")
            return jsonify({'error': 'Invalid payload'}), 400
        
        print(f"📦 Payload keys: {list(payload.keys())}")
        print(f"📦 Payload type: {payload.get('type')}")
        print(f"📦 Payload action: {payload.get('action')}")
        
        # Verify timestamp to prevent replay attacks
        print("⏰ Verifying webhook timestamp...")
        timestamp_valid = verify_webhook_timestamp(payload)
        if not timestamp_valid:
            print("❌ Webhook timestamp verification failed")
            abort(401, 'Invalid timestamp')
        print("✅ Timestamp verification passed")
        
        # Verify webhook type
        webhook_type = payload.get('type')
        print(f"🔍 Webhook type: {webhook_type}")
        
        if webhook_type == 'ProjectUpdate':
            print("🚀 Processing ProjectUpdate webhook...")
            success = process_project_update_webhook(payload)
            if success:
                print("✅ Successfully processed webhook")
                return jsonify({'status': 'success'}), 200
            else:
                print("❌ Failed to process webhook")
                return jsonify({'status': 'error', 'message': 'Failed to process update'}), 500
        else:
            print(f"⚠️  Ignoring webhook type: {webhook_type}")
            return jsonify({'status': 'ignored'}), 200
            
    except Exception as e:
        print(f"❌ Error handling webhook: {e}")
        import traceback
        traceback.print_exc()
        # Don't expose internal errors to potential attackers
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        print("="*60 + "\n")


@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    """
    return jsonify({'status': 'ok'}), 200


@app.before_request
def log_request_info():
    """
    Log all incoming requests for debugging.
    """
    if request.path != '/health':  # Don't log health checks
        print(f"\n🌐 Incoming request: {request.method} {request.path}")
        if request.path != '/webhook':
            print(f"   ⚠️  Request to {request.path} - this endpoint doesn't exist!")
            print(f"   💡 Webhook endpoint is at: /webhook")
            print(f"   💡 Make sure your Linear webhook URL ends with /webhook")


def main():
    """
    Main function to start the webhook server.
    """
    # Validate configuration
    if not NOTION_API_KEY:
        print("Error: NOTION_API_KEY not set in .env file")
        return
    
    if not NOTION_DATABASE_ID:
        print("Error: NOTION_DATABASE_ID not set in .env file")
        return
    
    port = int(os.getenv('PORT', 8000))
    
    # Set up ngrok for local testing if enabled
    public_url = None
    if USE_NGROK:
        if not NGROK_AVAILABLE:
            print("Warning: pyngrok not installed. Install it with: pip install pyngrok")
            print("Or set USE_NGROK=false in .env to disable ngrok")
        else:
            try:
                # Set ngrok auth token if provided
                if NGROK_AUTH_TOKEN:
                    ngrok.set_auth_token(NGROK_AUTH_TOKEN)  # type: ignore
                
                # Start ngrok tunnel
                public_url = ngrok.connect(port)  # type: ignore
                print("\n" + "="*60)
                print("🚀 ngrok tunnel established!")
                print("="*60)
                print(f"Public URL: {public_url}")
                print(f"Webhook endpoint: {public_url}/webhook")
                print(f"Health check: {public_url}/health")
                print("\n⚠️  Copy the webhook URL above and use it in Linear webhook settings")
                print("="*60 + "\n")
            except Exception as e:
                print(f"Error starting ngrok: {e}")
                print("Continuing without ngrok...")
                public_url = None
    
    if not public_url:
        print("Starting Linear to Notion webhook server...")
        print(f"Local webhook endpoint: http://localhost:{port}/webhook")
        print(f"Local health check: http://localhost:{port}/health")
        if not USE_NGROK:
            print("\n💡 To test with Linear webhooks locally, set USE_NGROK=true in .env")
            print("   and optionally set NGROK_AUTH_TOKEN for authenticated ngrok sessions\n")
    
    # Run Flask app
    # In production, use a proper WSGI server like gunicorn
    try:
        app.run(host='0.0.0.0', port=port, debug=True)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        if public_url and NGROK_AVAILABLE:
            ngrok.disconnect(public_url)  # type: ignore
            print("ngrok tunnel closed")


if __name__ == '__main__':
    main()
