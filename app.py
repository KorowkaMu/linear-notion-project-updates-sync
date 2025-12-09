"""
Linear to Notion Sync
Automates posting Linear Project Updates to Notion pages via webhooks. Also updates the Contact property with the author of the update.
"""

import os
import hmac
import hashlib
import time
import json
import re
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, abort
from dotenv import load_dotenv

# Optional schedule import for cron jobs
schedule = None  # type: ignore
SCHEDULE_AVAILABLE = False
try:
    import schedule  # type: ignore
    SCHEDULE_AVAILABLE = True
except ImportError:
    pass

# Optional ngrok import for local testing
try:
    from pyngrok import ngrok
    NGROK_AVAILABLE = True
except ImportError:
    NGROK_AVAILABLE = False

# Optional OpenAI and Pydantic imports
OPENAI_AVAILABLE = False
PYDANTIC_AVAILABLE = False
try:
    import openai  # type: ignore
    OPENAI_AVAILABLE = True
except ImportError:
    pass

try:
    from pydantic import BaseModel  # type: ignore
    from typing import Optional, List, Union  # type: ignore
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = None  # type: ignore
    Optional = None  # type: ignore
    List = None  # type: ignore
    Union = None  # type: ignore
    PYDANTIC_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configuration
LINEAR_API_KEY = os.getenv('LINEAR_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
NOTION_ALL_UPDATES_DATABASE_ID = os.getenv('NOTION_ALL_UPDATES_DATABASE_ID')
LINEAR_WEBHOOK_SECRET = os.getenv('LINEAR_WEBHOOK_SECRET', '')


def format_notion_id(notion_id):
    """
    Format a Notion ID to include dashes if missing.
    Notion IDs are UUIDs that can be provided with or without dashes.
    """
    if not notion_id:
        return None
    
    # Remove any existing dashes and whitespace
    clean_id = notion_id.replace('-', '').strip()
    
    # Check if it's a valid UUID length (32 characters)
    if len(clean_id) != 32:
        return notion_id  # Return as-is if not valid length
    
    # Format as UUID: 8-4-4-4-12
    formatted = f"{clean_id[0:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:32]}"
    return formatted


# Format database IDs to ensure they have dashes
if NOTION_DATABASE_ID:
    NOTION_DATABASE_ID = format_notion_id(NOTION_DATABASE_ID)
if NOTION_ALL_UPDATES_DATABASE_ID:
    NOTION_ALL_UPDATES_DATABASE_ID = format_notion_id(NOTION_ALL_UPDATES_DATABASE_ID)
USE_NGROK = os.getenv('USE_NGROK', 'false').lower() == 'true'
NGROK_AUTH_TOKEN = os.getenv('NGROK_AUTH_TOKEN', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')

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


def get_project_teams(project_id):
    """
    Fetch project details including teams from Linear using GraphQL API.
    Returns a list of team names.
    """
    if not LINEAR_API_KEY:
        print("   ⚠️  LINEAR_API_KEY not set, cannot fetch project teams")
        return []
    
    headers = {
        'Authorization': LINEAR_API_KEY,
        'Content-Type': 'application/json',
    }
    
    query = """
    query($id: String!) {
      project(id: $id) {
        id
        name
        teams {
          nodes {
            id
            name
          }
        }
      }
    }
    """
    
    try:
        print(f"   🔍 Fetching project teams from Linear API for project: {project_id}")
        response = requests.post(
            LINEAR_API_URL,
            json={'query': query, 'variables': {'id': project_id}},
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            project = data.get('data', {}).get('project', {})
            
            if not project:
                print(f"   ⚠️  Project not found: {project_id}")
                return []
            
            team_names = []
            
            # Check for multiple teams (teams.nodes)
            teams = project.get('teams', {}).get('nodes', [])
            if teams:
                team_names = [team.get('name') for team in teams if team.get('name')]
                print(f"   ✅ Found {len(team_names)} team(s): {', '.join(team_names)}")
            else:
                print(f"   ⚠️  No teams found for project")
            
            return team_names
        else:
            print(f"   ⚠️  Error fetching project: {response.status_code}")
            print(f"   Response: {response.text}")
            return []
    except Exception as e:
        print(f"   ❌ Exception fetching project teams: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_project_status(project_id):
    """
    Fetch project status from Linear using GraphQL API.
    Returns the project status string, or None if not found.
    """
    if not LINEAR_API_KEY:
        print("   ⚠️  LINEAR_API_KEY not set, cannot fetch project status")
        return None
    
    headers = {
        'Authorization': LINEAR_API_KEY,
        'Content-Type': 'application/json',
    }
    
    query = """
    query($id: String!) {
      project(id: $id) {
        id
        name
        status {
          name
          type
        }
      }
    }
    """
    
    try:
        print(f"   🔍 Fetching project status from Linear API for project: {project_id}")
        response = requests.post(
            LINEAR_API_URL,
            json={'query': query, 'variables': {'id': project_id}},
            headers=headers
        )
        
        if response.status_code == 200:
            data = response.json()
            project = data.get('data', {}).get('project', {})
            
            if not project:
                print(f"   ⚠️  Project not found: {project_id}")
                return None
            
            status_obj = project.get('status')
            if status_obj:
                # Status is an object, get the name field
                status = status_obj.get('name')
                if status:
                    print(f"   ✅ Found project status: {status}")
                else:
                    print(f"   ⚠️  Status object found but no name field: {status_obj}")
                    return None
            else:
                print(f"   ⚠️  No status found for project")
                return None
            
            return status
        else:
            print(f"   ⚠️  Error fetching project status: {response.status_code}")
            print(f"   Response: {response.text}")
            return None
    except Exception as e:
        print(f"   ❌ Exception fetching project status: {e}")
        import traceback
        traceback.print_exc()
        return None


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
    Calculate the "Week ending on" date based on company rules.
    Returns the date as a datetime object.
    
    Company rule: Updates are written on Friday, but teams can be late and 
    continue adding/updating on Saturday, Sunday, and Monday. Those late 
    updates should still use the previous Friday's date.
    
    - Friday, Saturday, Sunday, Monday: use the most recent Friday
      (today if Friday, or previous Friday if Sat/Sun/Mon)
    - Tuesday, Wednesday, Thursday: use the upcoming Friday (this week)
    """
    today = datetime.now()
    # Get the day of the week (Monday=0, Sunday=6)
    days_since_monday = today.weekday()
    
    # Friday is day 4 (0=Monday, 4=Friday, 6=Sunday)
    if days_since_monday == 0:
        # Monday: go back to the previous Friday (3 days ago)
        week_ending_friday = today - timedelta(days=3)
    elif days_since_monday <= 3:
        # Tuesday (1), Wednesday (2), Thursday (3): calculate days until Friday
        days_until_friday = 4 - days_since_monday
        week_ending_friday = today + timedelta(days=days_until_friday)
    elif days_since_monday == 4:
        # Friday: use today
        week_ending_friday = today
    else:
        # Saturday (5) or Sunday (6): go back to the previous Friday
        days_since_friday = days_since_monday - 4
        week_ending_friday = today - timedelta(days=days_since_friday)
    
    return week_ending_friday


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
    Find or create a Notion document with the format: "{{team}} Update"
    Searches by title AND "Week ending on" property to find existing documents.
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
    
    document_title = f"{team_name} Update"
    print(f"   Searching for document: '{document_title}'")
    
    # Calculate the week ending date (last Friday) for filtering
    last_friday = get_last_friday_of_week()
    week_ending_date = last_friday.strftime('%Y-%m-%d')
    print(f"   Week ending on: {week_ending_date}")
    
    # First, try to find existing document by querying the database
    query_url = f'{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}/query'
    print(f"   Query URL: {query_url}")
    
    try:
        # Query database for existing document with matching title AND week ending date
        print("   🔍 Querying Notion database...")
        query_response = requests.post(
            query_url,
            json={
                'filter': {
                    'and': [
                        {
                            'property': 'Name',
                            'title': {
                                'equals': document_title
                            }
                        },
                        {
                            'property': 'Week ending on',
                            'date': {
                                'equals': week_ending_date
                            }
                        }
                    ]
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


# Pydantic models for Notion blocks
# Define these conditionally to avoid errors if Pydantic is not available
NotionBlocksResponse = None  # type: ignore
if PYDANTIC_AVAILABLE and BaseModel is not None:
    from typing import Any, Dict  # type: ignore
    from pydantic import ConfigDict  # type: ignore
    
    # Define a flexible block model that can handle different block types
    # OpenAI's structured output requires additionalProperties: false
    # So we explicitly define all possible block type fields as optional
    class NotionBlock(BaseModel):  # type: ignore
        object: str = "block"
        type: str
        # Define all possible block type fields as optional
        paragraph: Optional[Dict[str, Any]] = None  # type: ignore
        embed: Optional[Dict[str, Any]] = None  # type: ignore
        heading_1: Optional[Dict[str, Any]] = None  # type: ignore
        heading_2: Optional[Dict[str, Any]] = None  # type: ignore
        heading_3: Optional[Dict[str, Any]] = None  # type: ignore
        bulleted_list_item: Optional[Dict[str, Any]] = None  # type: ignore
        numbered_list_item: Optional[Dict[str, Any]] = None  # type: ignore
        # Forbid extra properties to satisfy OpenAI's requirement
        model_config = ConfigDict(extra="forbid")
    
    class NotionBlocksResponse(BaseModel):  # type: ignore
        blocks: List[NotionBlock]  # type: ignore


def convert_content_with_llm(update_body):
    """
    Use OpenAI LLM to convert Linear project update content into Notion-compatible format.
    Returns a list of Notion block objects, or None if the LLM call fails.
    """
    if not OPENAI_AVAILABLE:
        print("   ⚠️  OpenAI library not available")
        return None

    if not OPENAI_API_KEY:
        print("   ⚠️  OPENAI_API_KEY not set")
        return None

    if not update_body or not update_body.strip():
        return None

    try:
        print("   🤖 Using LLM to convert content to Notion format...")

        # Initialize OpenAI client
        client = openai.OpenAI(api_key=OPENAI_API_KEY)  # type: ignore

        # Prompt for the LLM – we ask explicitly for JSON with { "blocks": [...] }
        prompt = f"""Convert the following Linear project update content into Notion-compatible format.

The content may contain:
- Plain text
- URLs/links (including Linear, Loom, YouTube, etc.)
- Markdown formatting
- Lists
- Other formatting

Return a JSON object with the following shape, and NOTHING else:

{{
  "blocks": [
    {{
      "object": "block",
      "type": "paragraph" | "embed" | "heading_1" | "heading_2" | "heading_3" | "bulleted_list_item" | "numbered_list_item",
      "<type-specific-key>": {{
        // Notion's API-compatible payload
      }}
    }},
    ...
  ]
}}

Guidelines:
- Use "paragraph" blocks for normal text.
- Do NOT create heading blocks if not explicitly present in the original content.

- IF heading blocks are present in the original content (heading_1, heading_2, heading_3), ALWAYS use "rich_text" array, NEVER use "text" field:
  {{
    "object": "block",
    "type": "heading_1",
    "heading_1": {{
      "rich_text": [
        {{
          "type": "text",
          "text": {{
            "content": "Heading text here"
          }}
        }}
      ]
    }}
  }}
  IMPORTANT: Do NOT use "text" field directly in heading blocks. Always use "rich_text" array.

- For paragraph blocks, use "rich_text" array:
  {{
    "object": "block",
    "type": "paragraph",
    "paragraph": {{
      "rich_text": [
        {{
          "type": "text",
          "text": {{
            "content": "Paragraph text here"
          }}
        }}
      ]
    }}
  }}

- For list items (bulleted_list_item, numbered_list_item), use "rich_text" array:
  {{
    "object": "block",
    "type": "bulleted_list_item",
    "bulleted_list_item": {{
      "rich_text": [
        {{
          "type": "text",
          "text": {{
            "content": "List item text"
          }}
        }}
      ]
    }}
  }}

- For ANY URL whose domain contains "linear.app", include it as an inline link within paragraph text using rich_text with link annotations:
  {{
    "type": "text",
    "text": {{
      "content": "Link text or URL",
      "link": {{
        "url": "https://linear.app/..."
      }}
    }}
  }}

- Place Linear URLs inline within paragraph blocks, not as separate embed blocks.

- Use "embed" blocks for video URLs (Loom, YouTube, Vimeo, etc.) in the same way:
  {{
    "object": "block",
    "type": "embed",
    "embed": {{
      "url": "https://..."
    }}
  }}

- For other inline links in text, use rich_text with link annotations.

- CRITICAL: All text content (paragraphs, headings, list items) MUST use "rich_text" array format. NEVER use a "text" field directly in block structures.

- Preserve the structure and meaning of the original content.

- Make sure the JSON is valid and parsable.

Content to convert:
{update_body}
"""

        completion = client.chat.completions.create(  # type: ignore
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that converts text content into Notion API block format. Always respond with a single valid JSON object."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            # Ask the model to respond with a JSON object
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        content = completion.choices[0].message.content
        if not content:
            print("   ⚠️  LLM returned empty content")
            return None

        try:
            response_data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"   ⚠️  Failed to parse LLM JSON: {e}")
            print(f"   Raw content: {content[:400]}...")
            return None

        blocks = response_data.get("blocks") or []
        if not isinstance(blocks, list) or not blocks:
            print("   ⚠️  LLM returned no blocks or blocks is not a list")
            return None

        # Normalize / ensure required fields
        normalized_blocks = []
        for i, block in enumerate(blocks):
            try:
                if not isinstance(block, dict):
                    print(f"   ⚠️  Block {i} is not a dict: {type(block)}, skipping")
                    continue

                block_dict = dict(block)

                if "object" not in block_dict:
                    block_dict["object"] = "block"
                if "type" not in block_dict:
                    block_dict["type"] = "paragraph"

                # Ensure embed blocks have the correct Notion shape
                if block_dict["type"] == "embed":
                    # Case 1: model put the URL directly as "url" on the block
                    if "embed" not in block_dict:
                        url = block_dict.get("url")
                        if url:
                            block_dict["embed"] = {"url": url}
                            block_dict.pop("url", None)
                    # Case 2: model returned "embed": "https://linear.app/..."
                    elif isinstance(block_dict["embed"], str):
                        block_dict["embed"] = {"url": block_dict["embed"]}
                
                # Ensure paragraph blocks have the correct Notion shape
                if block_dict["type"] == "paragraph":
                    if "paragraph" not in block_dict:
                        block_dict["paragraph"] = {}
                    
                    # Check if LLM used "text" instead of "rich_text" (common mistake)
                    if "text" in block_dict["paragraph"]:
                        # Convert "text" to "rich_text"
                        text_value = block_dict["paragraph"].pop("text")
                        if isinstance(text_value, list):
                            block_dict["paragraph"]["rich_text"] = text_value
                        else:
                            # If it's not a list, wrap it
                            block_dict["paragraph"]["rich_text"] = [text_value] if text_value else []
                    
                    if "rich_text" not in block_dict["paragraph"]:
                        # If rich_text is missing, create an empty array
                        block_dict["paragraph"]["rich_text"] = []
                    # Ensure rich_text is a list
                    elif not isinstance(block_dict["paragraph"]["rich_text"], list):
                        # If it's not a list, wrap it or create empty
                        block_dict["paragraph"]["rich_text"] = []
                    else:
                        # Normalize rich_text items to ensure correct structure
                        normalized_rich_text = []
                        for rt_item in block_dict["paragraph"]["rich_text"]:
                            if isinstance(rt_item, dict):
                                # If text field is a string, convert it to object
                                if "text" in rt_item and isinstance(rt_item["text"], str):
                                    rt_item = {
                                        "type": rt_item.get("type", "text"),
                                        "text": {
                                            "content": rt_item["text"]
                                        }
                                    }
                                # NEW: always move top-level "link" into text.link, if possible
                                if "link" in rt_item:
                                    link_val = rt_item.pop("link")
                                    if isinstance(rt_item.get("text"), dict):
                                        rt_item["text"]["link"] = link_val
                                
                                # Ensure type is set
                                if "type" not in rt_item:
                                    rt_item["type"] = "text"
                                normalized_rich_text.append(rt_item)
                            elif isinstance(rt_item, str):
                                # If it's just a string, convert to proper rich_text format
                                normalized_rich_text.append({
                                    "type": "text",
                                    "text": {
                                        "content": rt_item
                                    }
                                })
                        block_dict["paragraph"]["rich_text"] = normalized_rich_text
                
                # Ensure heading blocks have the correct Notion shape
                if block_dict["type"] in ["heading_1", "heading_2", "heading_3"]:
                    heading_key = block_dict["type"]
                    if heading_key not in block_dict:
                        block_dict[heading_key] = {}
                    
                    # Remove any top-level "text" field from heading block (invalid structure)
                    if "text" in block_dict[heading_key]:
                        print(f"   ⚠️  Removing invalid 'text' field from {heading_key} block")
                        block_dict[heading_key].pop("text", None)
                    
                    # Check if LLM used "text" instead of "rich_text" (common mistake)
                    if "text" in block_dict[heading_key]:
                        # Convert "text" to "rich_text"
                        text_value = block_dict[heading_key].pop("text")
                        if isinstance(text_value, list):
                            block_dict[heading_key]["rich_text"] = text_value
                        else:
                            block_dict[heading_key]["rich_text"] = [text_value] if text_value else []
                    
                    if "rich_text" not in block_dict[heading_key]:
                        block_dict[heading_key]["rich_text"] = []
                    elif not isinstance(block_dict[heading_key]["rich_text"], list):
                        block_dict[heading_key]["rich_text"] = []
                    else:
                        # Normalize rich_text items (same as paragraph)
                        normalized_rich_text = []
                        for rt_item in block_dict[heading_key]["rich_text"]:
                            if isinstance(rt_item, dict):
                                if "text" in rt_item and isinstance(rt_item["text"], str):
                                    rt_item = {
                                        "type": rt_item.get("type", "text"),
                                        "text": {
                                            "content": rt_item["text"]
                                        }
                                    }
                                # NEW: move top-level link into text.link
                                if "link" in rt_item:
                                    link_val = rt_item.pop("link")
                                    if isinstance(rt_item.get("text"), dict):
                                        rt_item["text"]["link"] = link_val
                                
                                if "type" not in rt_item:
                                    rt_item["type"] = "text"
                                normalized_rich_text.append(rt_item)
                            elif isinstance(rt_item, str):
                                normalized_rich_text.append({
                                    "type": "text",
                                    "text": {
                                        "content": rt_item
                                    }
                                })
                        block_dict[heading_key]["rich_text"] = normalized_rich_text
                
                # Ensure list item blocks have the correct Notion shape
                if block_dict["type"] in ["bulleted_list_item", "numbered_list_item"]:
                    list_key = block_dict["type"]
                    if list_key not in block_dict:
                        block_dict[list_key] = {}
                    
                    # NEW: convert "text" -> "rich_text" and remove "text"
                    if "text" in block_dict[list_key]:
                        text_value = block_dict[list_key].pop("text")
                        if isinstance(text_value, list):
                            block_dict[list_key]["rich_text"] = text_value
                        else:
                            block_dict[list_key]["rich_text"] = [text_value] if text_value else []
                    
                    if "rich_text" not in block_dict[list_key]:
                        block_dict[list_key]["rich_text"] = []
                    elif not isinstance(block_dict[list_key]["rich_text"], list):
                        block_dict[list_key]["rich_text"] = []
                    else:
                        # Normalize rich_text items (same as paragraph)
                        normalized_rich_text = []
                        for rt_item in block_dict[list_key]["rich_text"]:
                            if isinstance(rt_item, dict):
                                # If text field is a string, convert it to object
                                if "text" in rt_item and isinstance(rt_item["text"], str):
                                    rt_item = {
                                        "type": rt_item.get("type", "text"),
                                        "text": {
                                            "content": rt_item["text"]
                                        }
                                    }
                                # NEW: move top-level link into text.link
                                if "link" in rt_item:
                                    link_val = rt_item.pop("link")
                                    if isinstance(rt_item.get("text"), dict):
                                        rt_item["text"]["link"] = link_val
                                
                                if "type" not in rt_item:
                                    rt_item["type"] = "text"
                                normalized_rich_text.append(rt_item)
                            elif isinstance(rt_item, str):
                                normalized_rich_text.append({
                                    "type": "text",
                                    "text": {
                                        "content": rt_item
                                    }
                                })
                        block_dict[list_key]["rich_text"] = normalized_rich_text

                normalized_blocks.append(block_dict)
            except Exception as e:
                print(f"   ⚠️  Error normalizing block {i}: {e}")
                import traceback
                traceback.print_exc()
                # Skip this block and continue
                continue

        if not normalized_blocks:
            print("   ⚠️  LLM returned no valid blocks after normalization")
            return None

        print(f"   ✅ LLM converted content into {len(normalized_blocks)} block(s)")
        return normalized_blocks

    except Exception as e:
        print(f"   ⚠️  LLM conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def convert_content_with_fallback(update_body):
    """
    Fallback function to convert content by detecting and properly formatting links.
    Returns a list of Notion block objects.
    """
    if not update_body or not update_body.strip():
        return []
    
    print("   📝 Using fallback script to handle links...")
    
    # Pattern to detect URLs
    url_pattern = r'https?://[^\s\)\]\}]+'
    
    # Find all URLs in the text
    urls = []
    for match in re.finditer(url_pattern, update_body):
        url = match.group(0)
        # Remove trailing punctuation
        url = url.rstrip('.,;:!?)')
        urls.append((match.start(), match.start() + len(url), url))
    
    if not urls:
        # No URLs found, return simple paragraph
        return [{
            'object': 'block',
            'type': 'paragraph',
            'paragraph': {
                'rich_text': [{
                    'type': 'text',
                    'text': {
                        'content': update_body
                    }
                }]
            }
        }]
    
    # Build rich_text array with links
    rich_text = []
    last_end = 0
    
    for start, end, url in urls:
        # Add text before the URL
        if start > last_end:
            text_segment = update_body[last_end:start]
            if text_segment:
                rich_text.append({
                    'type': 'text',
                    'text': {
                        'content': text_segment
                    }
                })
        
        # Add the URL as a link
        # Extract link text (could be the URL itself or text before it)
        link_text = url
        rich_text.append({
            'type': 'text',
            'text': {
                'content': link_text,
                'link': {
                    'url': url
                }
            }
        })
        last_end = end
    
    # Add remaining text after the last URL
    if last_end < len(update_body):
        text_segment = update_body[last_end:]
        if text_segment:
            rich_text.append({
                'type': 'text',
                'text': {
                    'content': text_segment
                }
            })
    
    return [{
        'object': 'block',
        'type': 'paragraph',
        'paragraph': {
            'rich_text': rich_text
        }
    }]


def find_update_blocks(page_id, update_id):
    """
    Find all blocks belonging to a Linear update with the given ID.
    Returns a tuple: (found: bool, block_ids: list) where block_ids contains
    the IDs of blocks to delete (from heading to callout marker inclusive).
    """
    if not NOTION_API_KEY or not update_id:
        return False, []
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        # Fetch all blocks from the page (handle pagination)
        blocks_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
        all_blocks = []
        next_cursor = None
        
        while True:
            params = {'page_size': 100}
            if next_cursor:
                params['start_cursor'] = next_cursor
            
            response = requests.get(blocks_url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"   ⚠️  Could not fetch blocks: {response.status_code}")
                break
            
            data = response.json()
            blocks = data.get('results', [])
            all_blocks.extend(blocks)
            
            # Check if there are more pages
            has_more = data.get('has_more', False)
            next_cursor = data.get('next_cursor')
            
            if not has_more or not next_cursor:
                break
        
        # Find the end marker (paragraph) and then search backwards for the divider start marker
        end_marker = f"linear-update-id:{update_id}"
        end_index = None
        
        # First, find the end marker paragraph
        for i, block in enumerate(all_blocks):
            block_type = block.get('type')
            if block_type == 'paragraph':
                paragraph = block.get('paragraph', {})
                rich_text = paragraph.get('rich_text', [])
                for rt in rich_text:
                    text_content = rt.get('text', {}).get('content', '')
                    if end_marker in text_content:
                        end_index = i
                        break
            if end_index is not None:
                break
        
        if end_index is None:
            return False, []
        
        # Now search backwards from the end marker to find the divider that starts this update
        # The divider should be followed by a heading_2 with the project name
        start_index = None
        for i in range(end_index - 1, -1, -1):
            block = all_blocks[i]
            block_type = block.get('type')
            
            # Look for a divider that is followed by a heading_2
            if block_type == 'divider':
                # Check if the next block is a heading_2
                if i + 1 < len(all_blocks):
                    next_block = all_blocks[i + 1]
                    if next_block.get('type') == 'heading_2':
                        # This divider is likely our start marker
                        # Verify by checking there's no other divider between this and the end marker
                        # (to avoid matching the wrong divider if there are multiple updates)
                        start_index = i
                        break
        
        if start_index is None:
            return False, []
        
        # Collect all block IDs from divider (start) to end marker (inclusive)
        block_ids_to_delete = []
        for i in range(start_index, end_index + 1):
            block_id = all_blocks[i].get('id')
            if block_id:
                block_ids_to_delete.append(block_id)
        
        return True, block_ids_to_delete
        
    except Exception as e:
        print(f"   ⚠️  Error finding update blocks: {e}")
        import traceback
        traceback.print_exc()
        return False, []


def check_update_already_exists(page_id, update_id):
    """
    Check if a Linear update with the given ID already exists in the Notion page.
    Returns True if the update already exists, False otherwise.
    """
    if not NOTION_API_KEY or not update_id:
        return False
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        # Fetch all blocks from the page (handle pagination)
        blocks_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
        all_blocks = []
        next_cursor = None
        
        while True:
            params = {'page_size': 100}
            if next_cursor:
                params['start_cursor'] = next_cursor
            
            response = requests.get(blocks_url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"   ⚠️  Could not fetch blocks to check for duplicates: {response.status_code}")
                break
            
            data = response.json()
            blocks = data.get('results', [])
            all_blocks.extend(blocks)
            
            # Check if there are more pages
            has_more = data.get('has_more', False)
            next_cursor = data.get('next_cursor')
            
            if not has_more or not next_cursor:
                break
        
        # Check each block for the update ID
        # We'll store it in a callout block with a specific format
        update_id_marker = f"linear-update-id:{update_id}"
        
        for block in all_blocks:
            block_type = block.get('type')
            if block_type == 'callout':
                callout = block.get('callout', {})
                rich_text = callout.get('rich_text', [])
                # Check if any rich_text contains the update ID marker
                for rt in rich_text:
                    text_content = rt.get('text', {}).get('content', '')
                    if update_id_marker in text_content:
                        print(f"   ✅ Found existing update with ID: {update_id}")
                        return True
            elif block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3']:
                # Also check headings and paragraphs for the marker
                block_data = block.get(block_type, {})
                rich_text = block_data.get('rich_text', [])
                for rt in rich_text:
                    text_content = rt.get('text', {}).get('content', '')
                    if update_id_marker in text_content:
                        print(f"   ✅ Found existing update with ID: {update_id}")
                        return True
        
        return False
        
    except Exception as e:
        print(f"   ⚠️  Error checking for duplicate update: {e}")
        import traceback
        traceback.print_exc()
        return False


def delete_blocks(block_ids, headers):
    """
    Delete multiple blocks from Notion.
    """
    if not block_ids:
        return True
    
    success_count = 0
    for block_id in block_ids:
        try:
            delete_url = f'{NOTION_API_URL}/blocks/{block_id}'
            response = requests.delete(delete_url, headers=headers)
            if response.status_code == 200:
                success_count += 1
            else:
                print(f"   ⚠️  Failed to delete block {block_id}: {response.status_code}")
        except Exception as e:
            print(f"   ⚠️  Error deleting block {block_id}: {e}")
    
    print(f"   🗑️  Deleted {success_count}/{len(block_ids)} blocks")
    return success_count == len(block_ids)


def get_status_emoji(status):
    """Get emoji for status."""
    status_lower = (status or '').lower()
    if status_lower == 'ontrack' or status_lower == 'on_track':
        return '🟢'
    elif status_lower == 'atrisk' or status_lower == 'at_risk':
        return '🟡'
    elif status_lower == 'offtrack' or status_lower == 'off_track':
        return '🔴'
    return '⚪'


def format_status_text(status):
    """Format status text for display (lowercase)."""
    if not status:
        return None
    status_lower = status.lower()
    if status_lower in ['ontrack', 'on_track']:
        return 'on track'
    elif status_lower in ['atrisk', 'at_risk']:
        return 'at risk'
    elif status_lower in ['offtrack', 'off_track']:
        return 'off track'
    return status.lower()


def add_project_update_block(page_id, project_name, update_body, project_url=None, update_id=None, action='create', project_status=None, update_status=None, add_marker=True):
    """
    Add a new block to a Notion page with project name as heading and update content.
    If action is 'update' and the update already exists, replace it.
    
    Args:
        page_id: Notion page ID
        project_name: Name of the Linear project
        update_body: Content of the update
        project_url: Optional URL to the Linear project
        update_id: Optional Linear update ID for deduplication
        action: 'create' or 'update' - determines if we skip duplicates or replace them
        project_status: Optional project status (onTrack, atRisk, offTrack)
        update_status: Optional update status (onTrack, atRisk, offTrack)
        add_marker: Whether to add the linear-update-id marker (default: True)
    """
    if not NOTION_API_KEY:
        print("   ❌ Error: NOTION_API_KEY not set")
        return False
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    # Create blocks: heading with project name and status, then status indicator, then content
    # Build heading rich text with project name and status
    heading_parts = []
    
    # Add project name
    project_name_text = {
        'type': 'text',
        'text': {
            'content': project_name
        }
    }
    if project_url:
        project_name_text['text']['link'] = {'url': project_url}
    heading_parts.append(project_name_text)
    
    # Start with a divider line before the heading for reliable deduplication
    # This divider serves as the start marker
    blocks = []
    if update_id:
        # Add a divider (line) before the heading - this is our start marker
        blocks.append({
            'object': 'block',
            'type': 'divider',
            'divider': {}
        })
    
    # Add the heading block
    blocks.append({
        'object': 'block',
        'type': 'heading_2',
        'heading_2': {
            'rich_text': heading_parts
        }
    })
    
    # Add combined project status and update health beneath the heading
    # Format: icon + project status + ": " + update health
    if project_status or update_status:
        status_parts = []
        
        # Determine color based on update health
        status_color = 'gray'
        if update_status:
            status_lower = (update_status or '').lower()
            if status_lower in ['ontrack', 'on_track']:
                status_color = 'green'
            elif status_lower in ['atrisk', 'at_risk']:
                status_color = 'yellow'
            elif status_lower in ['offtrack', 'off_track']:
                status_color = 'red'
        
        # Build the combined status text
        if update_status:
            status_text = format_status_text(update_status)
            status_emoji = get_status_emoji(update_status)
            if status_text:
                # Add icon
                status_parts.append({
                    'type': 'text',
                    'text': {
                        'content': status_emoji
                    },
                    'annotations': {
                        'color': status_color,
                        'code': False,
                        'bold': False,
                        'italic': False,
                        'strikethrough': False,
                        'underline': False
                    }
                })
                
                # Add project status + ": " if available
                if project_status:
                    status_parts.append({
                        'type': 'text',
                        'text': {
                            'content': f' {project_status}: '
                        },
                        'annotations': {
                            'color': status_color,
                            'code': False,
                            'bold': False,
                            'italic': False,
                            'strikethrough': False,
                            'underline': False
                        }
                    })
                else:
                    # Add space after icon if no project status
                    status_parts.append({
                        'type': 'text',
                        'text': {
                            'content': ' '
                        },
                        'annotations': {
                            'color': status_color,
                            'code': False,
                            'bold': False,
                            'italic': False,
                            'strikethrough': False,
                            'underline': False
                        }
                    })
                
                # Add update health value
                status_parts.append({
                    'type': 'text',
                    'text': {
                        'content': status_text
                    },
                    'annotations': {
                        'color': status_color,
                        'code': False,
                        'bold': False,
                        'italic': False,
                        'strikethrough': False,
                        'underline': False
                    }
                })
        elif project_status:
            # If only project status is available (no update health), just show it
            status_parts.append({
                'type': 'text',
                'text': {
                    'content': project_status
                },
                'annotations': {
                    'color': 'gray',
                    'code': False,
                    'bold': False,
                    'italic': False,
                    'strikethrough': False,
                    'underline': False
                }
            })
        
        if status_parts:
            blocks.append({
                'object': 'block',
                'type': 'paragraph',
                'paragraph': {
                    'rich_text': status_parts
                }
            })
    
    # Try to convert content using LLM, fallback to script-based approach if it fails
    content_blocks = None
    try:
        if update_body:
            content_blocks = convert_content_with_llm(update_body)
            if content_blocks is None:
                print("   ⚠️  LLM conversion failed, using fallback...")
                content_blocks = convert_content_with_fallback(update_body)
        
        # Add content blocks
        if content_blocks:
            # Validate blocks before extending
            if not isinstance(content_blocks, list):
                print(f"   ⚠️  content_blocks is not a list: {type(content_blocks)}")
                content_blocks = []
            else:
                # Validate each block is a dict
                valid_blocks = []
                for i, block in enumerate(content_blocks):
                    if isinstance(block, dict):
                        valid_blocks.append(block)
                    else:
                        print(f"   ⚠️  Block {i} is not a dict: {type(block)}, skipping")
                content_blocks = valid_blocks
            blocks.extend(content_blocks)
        else:
            # If no content blocks were created, add an empty paragraph
            blocks.append({
                'object': 'block',
                'type': 'paragraph',
                'paragraph': {
                    'rich_text': []
                }
            })
    except Exception as e:
        print(f"   ❌ Error processing content blocks: {e}")
        import traceback
        traceback.print_exc()
        # Fallback to empty paragraph if content processing fails
        blocks.append({
            'object': 'block',
            'type': 'paragraph',
            'paragraph': {
                'rich_text': []
            }
        })
    
    # Check for duplicate update before adding
    if update_id:
        exists, block_ids = find_update_blocks(page_id, update_id)
        if exists:
            if action == 'create':
                # For create actions, skip duplicates to avoid extra LLM costs
                print(f"   ⏭️  Skipping duplicate create (ID: {update_id})")
                return True  # Return True because we successfully handled it (by skipping)
            elif action == 'update':
                # For update actions, delete the old blocks and replace with new ones
                print(f"   🔄 Replacing existing update (ID: {update_id})")
                if block_ids:
                    delete_blocks(block_ids, headers)
                # Continue to add new blocks below
    
    print(f"   Adding blocks to page {page_id}")
    print(f"   Block 1: heading_2 with '{project_name}'")
    print(f"   Content blocks: {len(blocks) - 1}")
    
    # Add a plain paragraph block with gray text for the end marker (if provided)
    # This serves as a marker to prevent duplicates and identify update boundaries
    # Skip marker for "All project updates" database since we use properties for tracking
    if update_id and add_marker:
        blocks.append({
            'object': 'block',
            'type': 'paragraph',
            'paragraph': {
                'rich_text': [{
                    'type': 'text',
                    'text': {
                        'content': f'linear-update-id:{update_id}'
                    },
                    'annotations': {
                        'color': 'gray',
                        'code': False,
                        'bold': False,
                        'italic': False,
                        'strikethrough': False,
                        'underline': False
                    }
                }]
            }
        })
    
    # Final validation: ensure blocks are properly structured before sending to Notion
    for i, b in enumerate(blocks):
        t = b.get("type")
        
        # Remove any invalid "text" fields from heading blocks
        if t in ["heading_1", "heading_2", "heading_3"]:
            heading_key = t
            if heading_key in b:
                heading_obj = b[heading_key]
                if isinstance(heading_obj, dict) and "text" in heading_obj:
                    print(f"   ⚠️  Block {i}: Removing invalid 'text' field from {heading_key}")
                    heading_obj.pop("text", None)
                    # Ensure rich_text exists
                    if "rich_text" not in heading_obj:
                        heading_obj["rich_text"] = []
        
        # Debug check: ensure no top-level "link" in rich_text items
        if t in ["paragraph", "bulleted_list_item", "numbered_list_item", "heading_1", "heading_2", "heading_3"]:
            key = t if t.startswith("heading_") or t.endswith("_list_item") else "paragraph"
            inner = b.get(key, {})
            r = inner.get("rich_text", [])
            for j, rt in enumerate(r):
                if isinstance(rt, dict) and "link" in rt:
                    print(f"   ⚠️ rich_text[{j}] in block {i} still has top-level 'link': {rt}")
    
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


def get_database_title_property(database_id):
    """
    Get the title property name from a Notion database.
    Returns the property name, or None if not found.
    """
    if not NOTION_API_KEY:
        return None
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        response = requests.get(
            f'{NOTION_API_URL}/databases/{database_id}',
            headers=headers
        )
        
        if response.status_code == 200:
            db_info = response.json()
            properties = db_info.get('properties', {})
            
            # Find the title property (type == 'title')
            for prop_name, prop_data in properties.items():
                if prop_data.get('type') == 'title':
                    return prop_name
            
            # If no title property found, return None
            return None
        else:
            return None
    except Exception as e:
        print(f"   ⚠️  Error fetching database schema: {e}")
        return None


def find_existing_update_by_id(update_id):
    """
    Find an existing update document by linear-update-id.
    Returns (page_id, updated_at) if found, (None, None) otherwise.
    updated_at is the stored updatedAt timestamp from Linear.
    """
    if not NOTION_API_KEY or not NOTION_ALL_UPDATES_DATABASE_ID or not update_id:
        return None, None
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        query_url = f'{NOTION_API_URL}/databases/{NOTION_ALL_UPDATES_DATABASE_ID}/query'
        query_payload = {
            'filter': {
                'property': 'linear-update-id',
                'rich_text': {
                    'equals': update_id
                }
            },
            'page_size': 1
        }
        
        response = requests.post(query_url, json=query_payload, headers=headers)
        
        if response.status_code == 200:
            results = response.json().get('results', [])
            if results:
                page = results[0]
                page_id = page.get('id')
                
                # Get stored updatedAt timestamp
                props = page.get('properties', {})
                updated_at_prop = props.get('linear-updated-at', {})
                stored_updated_at = None
                
                # Prioritize rich_text (exact timestamp), fallback to date for backwards compatibility
                if updated_at_prop.get('type') == 'rich_text':
                    rich_text = updated_at_prop.get('rich_text', [])
                    if rich_text:
                        stored_updated_at = rich_text[0].get('text', {}).get('content', '').strip()
                elif updated_at_prop.get('type') == 'date':
                    date_obj = updated_at_prop.get('date', {})
                    if date_obj:
                        stored_updated_at = date_obj.get('start')
                
                return page_id, stored_updated_at
        
        return None, None
    except Exception as e:
        print(f"   ⚠️  Error finding existing update: {e}")
        return None, None


def find_or_create_all_updates_document(project_name, project_id, team_name, update_id, week_ending_date, updated_at=None):
    """
    Find or create a Notion document in the "All project updates" database.
    Each update creates a separate page with the project name as title.
    
    Args:
        project_name: Name of the Linear project (used as document title)
        project_id: Linear project ID (for deduplication)
        team_name: Team name(s) as string (e.g., "Team A & Team B")
        update_id: Linear update ID
        week_ending_date: Date string in YYYY-MM-DD format
        updated_at: Linear update updatedAt timestamp (ISO format)
    
    Returns:
        page_id if found or created, None otherwise
    """
    if not NOTION_API_KEY or not NOTION_ALL_UPDATES_DATABASE_ID:
        print("   ❌ Error: NOTION_API_KEY and NOTION_ALL_UPDATES_DATABASE_ID must be set")
        return None
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    # Get the title property name from the database schema
    title_property = get_database_title_property(NOTION_ALL_UPDATES_DATABASE_ID)
    if not title_property:
        print("   ⚠️  Could not find title property in database, trying 'Project name' as fallback")
        title_property = 'Project name'
    else:
        print(f"   📋 Using title property: '{title_property}'")
    
    # Determine if multi-team (check for "&" in team name)
    is_multi_team = " & " in team_name if team_name else False
    
    # Create a new page for each update (even if same project)
    print(f"   📝 Creating new update document in All updates database...")
    print(f"   Database ID being used: {NOTION_ALL_UPDATES_DATABASE_ID}")
    print(f"   Project: {project_name}")
    print(f"   Team: {team_name}")
    print(f"   Multi-team: {is_multi_team}")
    print(f"   Week ending on: {week_ending_date}")
    
    page_data = {
        'parent': {'database_id': NOTION_ALL_UPDATES_DATABASE_ID},
        'properties': {
            title_property: {
                'title': [
                    {
                        'text': {
                            'content': project_name
                        }
                    }
                ]
            },
            'Team': {
                'rich_text': [
                    {
                        'text': {
                            'content': team_name if team_name else ''
                        }
                    }
                ]
            },
            'Week ending on': {
                'date': {
                    'start': week_ending_date
                }
            },
            'linear-project-id': {
                'rich_text': [
                    {
                        'text': {
                            'content': project_id if project_id else ''
                        }
                    }
                ]
            },
            'linear-update-id': {
                'rich_text': [
                    {
                        'text': {
                            'content': update_id if update_id else ''
                        }
                    }
                ]
            },
            'multi-team': {
                'checkbox': is_multi_team
            }
        }
    }
    
    # Add updatedAt timestamp if provided
    if updated_at:
        # Store timestamp as rich_text to preserve exact format from Linear
        # Linear sends: "2025-12-08T21:23:20.860Z"
        # Store exactly as-is to avoid Notion date property rounding
        page_data['properties']['linear-updated-at'] = {
            'rich_text': [
                {
                    'text': {
                        'content': updated_at
                    }
                }
            ]
        }
    
    try:
        create_response = requests.post(
            f'{NOTION_API_URL}/pages',
            json=page_data,
            headers=headers
        )
        
        print(f"   Create response status: {create_response.status_code}")
        
        if create_response.status_code == 200:
            page_id = create_response.json()['id']
            print(f"   ✅ Created new update document: {page_id}")
            return page_id
        else:
            print(f"   ❌ Error creating update document: {create_response.status_code}")
            print(f"   Response: {create_response.text}")
            if create_response.status_code == 404:
                print(f"   💡 Troubleshooting:")
                print(f"      1. Verify the database ID is correct: {NOTION_ALL_UPDATES_DATABASE_ID}")
                print(f"      2. Make sure the database is shared with your Notion integration")
                print(f"      3. Check that the database exists and is accessible")
            return None
            
    except Exception as e:
        print(f"   ❌ Exception creating update document: {e}")
        import traceback
        traceback.print_exc()
        return None


def fetch_updates_for_week(week_ending_date):
    """
    Fetch all update records from All updates database for a specific week ending date.
    
    Args:
        week_ending_date: Date string in YYYY-MM-DD format
    
    Returns:
        List of page objects from Notion API
    """
    if not NOTION_API_KEY or not NOTION_ALL_UPDATES_DATABASE_ID:
        print("   ❌ Error: NOTION_API_KEY and NOTION_ALL_UPDATES_DATABASE_ID must be set")
        return []
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    query_url = f'{NOTION_API_URL}/databases/{NOTION_ALL_UPDATES_DATABASE_ID}/query'
    all_results = []
    next_cursor = None
    
    try:
        while True:
            query_payload = {
                'filter': {
                    'property': 'Week ending on',
                    'date': {
                        'equals': week_ending_date
                    }
                },
                'page_size': 100
            }
            
            if next_cursor:
                query_payload['start_cursor'] = next_cursor
            
            response = requests.post(query_url, json=query_payload, headers=headers)
            
            if response.status_code != 200:
                print(f"   ⚠️  Error querying database: {response.status_code}")
                print(f"   Response: {response.text}")
                break
            
            data = response.json()
            results = data.get('results', [])
            all_results.extend(results)
            
            has_more = data.get('has_more', False)
            next_cursor = data.get('next_cursor')
            
            if not has_more or not next_cursor:
                break
        
        print(f"   ✅ Fetched {len(all_results)} update records for week ending {week_ending_date}")
        return all_results
        
    except Exception as e:
        print(f"   ❌ Exception fetching updates: {e}")
        import traceback
        traceback.print_exc()
        return []


def deduplicate_updates(updates):
    """
    Remove duplicate updates for the same project, keeping the one with the freshest Last edited time.
    
    Args:
        updates: List of Notion page objects
    
    Returns:
        List of deduplicated updates
    """
    # Group by project ID
    project_updates = {}
    
    for update in updates:
        props = update.get('properties', {})
        project_id_prop = props.get('linear-project-id', {})
        project_id = None
        
        # Extract project ID from rich_text property
        if project_id_prop.get('type') == 'rich_text':
            rich_text = project_id_prop.get('rich_text', [])
            if rich_text:
                project_id = rich_text[0].get('text', {}).get('content', '').strip()
        
        if not project_id:
            # If no project ID, use project name as fallback
            # Try "Project name" first (for All updates database), then "Name" (for weekly updates database)
            name_prop = props.get('Project name', {}) or props.get('Name', {})
            if name_prop.get('type') == 'title':
                title = name_prop.get('title', [])
                if title:
                    project_id = title[0].get('text', {}).get('content', '').strip()
        
        if not project_id:
            # Skip updates without project identifier
            continue
        
        # Get last edited time
        last_edited = update.get('last_edited_time', '')
        
        if project_id not in project_updates:
            project_updates[project_id] = update
        else:
            # Compare last edited times and keep the fresher one
            existing_last_edited = project_updates[project_id].get('last_edited_time', '')
            if last_edited > existing_last_edited:
                project_updates[project_id] = update
    
    deduplicated = list(project_updates.values())
    print(f"   ✅ Deduplicated {len(updates)} updates to {len(deduplicated)} unique projects")
    return deduplicated


def get_update_content_blocks(page_id):
    """
    Fetch all content blocks from a Notion page.
    Returns blocks without dividers and linear-update-id markers.
    
    Args:
        page_id: Notion page ID
    
    Returns:
        List of block objects (filtered)
    """
    if not NOTION_API_KEY:
        return []
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    all_blocks = []
    next_cursor = None
    
    try:
        blocks_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
        
        while True:
            params = {'page_size': 100}
            if next_cursor:
                params['start_cursor'] = next_cursor
            
            response = requests.get(blocks_url, headers=headers, params=params)
            
            if response.status_code != 200:
                break
            
            data = response.json()
            blocks = data.get('results', [])
            all_blocks.extend(blocks)
            
            has_more = data.get('has_more', False)
            next_cursor = data.get('next_cursor')
            
            if not has_more or not next_cursor:
                break
        
        # Filter out dividers and linear-update-id markers, and convert to creation format
        filtered_blocks = []
        for block in all_blocks:
            block_type = block.get('type')
            
            # Skip dividers
            if block_type == 'divider':
                continue
            
            # Check all block types for linear-update-id markers
            # Extract text content from the block
            text_content = ''
            block_data = block.get(block_type, {})
            
            # Get rich_text from various block types
            if 'rich_text' in block_data:
                rich_text = block_data.get('rich_text', [])
                text_content = ''.join([rt.get('text', {}).get('content', '') for rt in rich_text])
            elif block_type in ['heading_1', 'heading_2', 'heading_3']:
                rich_text = block_data.get('rich_text', [])
                text_content = ''.join([rt.get('text', {}).get('content', '') for rt in rich_text])
            elif block_type in ['bulleted_list_item', 'numbered_list_item']:
                rich_text = block_data.get('rich_text', [])
                text_content = ''.join([rt.get('text', {}).get('content', '') for rt in rich_text])
            
            # Skip any block containing linear-update-id marker
            if 'linear-update-id:' in text_content:
                print(f"   🗑️  Filtering out block with linear-update-id marker: {block_type}")
                continue
            
            # Convert block to creation format (remove metadata, keep structure)
            new_block = {
                'object': 'block',
                'type': block_type
            }
            
            # Copy the type-specific content
            if block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3', 
                            'bulleted_list_item', 'numbered_list_item', 'to_do', 
                            'toggle', 'quote', 'callout', 'code', 'embed']:
                type_key = block_type
                if type_key in block:
                    block_content = block[type_key].copy()
                    
                    # Remove linear-update-id marker from rich_text if present
                    if 'rich_text' in block_content:
                        filtered_rich_text = []
                        for rt_item in block_content['rich_text']:
                            rt_text = rt_item.get('text', {}).get('content', '')
                            # Skip rich_text items that contain the marker
                            if 'linear-update-id:' not in rt_text:
                                filtered_rich_text.append(rt_item)
                            else:
                                print(f"   🗑️  Filtering out rich_text item with linear-update-id marker")
                        
                        # Only add block if there's still content after filtering
                        if filtered_rich_text:
                            block_content['rich_text'] = filtered_rich_text
                            new_block[type_key] = block_content
                        else:
                            # Skip this block entirely if all content was filtered
                            continue
                    else:
                        new_block[type_key] = block_content
                else:
                    new_block[type_key] = {}
            
            filtered_blocks.append(new_block)
        
        return filtered_blocks
        
    except Exception as e:
        print(f"   ⚠️  Error fetching blocks: {e}")
        return []


def generate_master_update(updates, week_ending_date):
    """
    Generate Master Update document content from deduplicated updates.
    Groups updates by team, with multi-team projects in a separate section.
    
    Args:
        updates: List of deduplicated Notion page objects
        week_ending_date: Date string in YYYY-MM-DD format
    
    Returns:
        List of blocks for the Master Update document
    """
    # Separate single-team and multi-team updates
    single_team_updates = {}
    multi_team_updates = []
    
    for update in updates:
        props = update.get('properties', {})
        multi_team_prop = props.get('multi-team', {})
        is_multi_team = multi_team_prop.get('checkbox', False) if multi_team_prop.get('type') == 'checkbox' else False
        
        if is_multi_team:
            multi_team_updates.append(update)
        else:
            # Get team name
            team_prop = props.get('Team', {})
            team_name = ''
            if team_prop.get('type') == 'rich_text':
                rich_text = team_prop.get('rich_text', [])
                if rich_text:
                    team_name = rich_text[0].get('text', {}).get('content', '').strip()
            
            if not team_name:
                # No team assigned, put in multi-team section
                multi_team_updates.append(update)
            else:
                if team_name not in single_team_updates:
                    single_team_updates[team_name] = []
                single_team_updates[team_name].append(update)
    
    # Sort updates within each team by last_edited_time (ascending)
    for team_name in single_team_updates:
        single_team_updates[team_name].sort(key=lambda x: x.get('last_edited_time', ''))
    multi_team_updates.sort(key=lambda x: x.get('last_edited_time', ''))
    
    # Build Master Update blocks
    master_blocks = []
    
    # Add team sections
    for team_name in sorted(single_team_updates.keys()):
        # Add team heading
        master_blocks.append({
            'object': 'block',
            'type': 'heading_1',
            'heading_1': {
                'rich_text': [{
                    'type': 'text',
                    'text': {
                        'content': team_name
                    }
                }]
            }
        })
        
        # Add updates for this team
        for update in single_team_updates[team_name]:
            page_id = update.get('id')
            content_blocks = get_update_content_blocks(page_id)
            master_blocks.extend(content_blocks)
    
    # Add multi-team section
    if multi_team_updates:
        master_blocks.append({
            'object': 'block',
            'type': 'heading_1',
            'heading_1': {
                'rich_text': [{
                    'type': 'text',
                    'text': {
                        'content': 'Multi-team projects'
                    }
                }]
            }
        })
        
        for update in multi_team_updates:
            page_id = update.get('id')
            content_blocks = get_update_content_blocks(page_id)
            master_blocks.extend(content_blocks)
    
    return master_blocks


def find_or_replace_master_update(week_ending_date, master_blocks):
    """
    Find or create Master Update document for a week, replacing it entirely if it exists.
    
    Args:
        week_ending_date: Date string in YYYY-MM-DD format
        master_blocks: List of blocks for the Master Update
    
    Returns:
        True if successful, False otherwise
    """
    if not NOTION_API_KEY or not NOTION_DATABASE_ID:
        print("   ❌ Error: NOTION_API_KEY and NOTION_DATABASE_ID must be set")
        return False
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    document_title = "Project Updates"
    
    # Try to find existing document
    query_url = f'{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}/query'
    
    try:
        query_response = requests.post(
            query_url,
            json={
                'filter': {
                    'and': [
                        {
                            'property': 'Name',
                            'title': {
                                'equals': document_title
                            }
                        },
                        {
                            'property': 'Week ending on',
                            'date': {
                                'equals': week_ending_date
                            }
                        }
                    ]
                },
                'page_size': 1
            },
            headers=headers
        )
        
        page_id = None
        if query_response.status_code == 200:
            results = query_response.json().get('results', [])
            if results:
                page_id = results[0]['id']
                print(f"   ✅ Found existing Master Update document: {page_id}")
                
                # Update icon to construction worker emoji
                try:
                    icon_update_response = requests.patch(
                        f'{NOTION_API_URL}/pages/{page_id}',
                        json={
                            'icon': {
                                'type': 'emoji',
                                'emoji': '👷'
                            }
                        },
                        headers=headers
                    )
                    if icon_update_response.status_code == 200:
                        print(f"   ✅ Updated icon to construction worker emoji")
                    else:
                        print(f"   ⚠️  Could not update icon: {icon_update_response.status_code}")
                except Exception as e:
                    print(f"   ⚠️  Error updating icon: {e}")
                
                # Delete all existing blocks
                blocks_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
                all_block_ids = []
                next_cursor = None
                
                while True:
                    params = {'page_size': 100}
                    if next_cursor:
                        params['start_cursor'] = next_cursor
                    
                    get_response = requests.get(blocks_url, headers=headers, params=params)
                    if get_response.status_code != 200:
                        break
                    
                    data = get_response.json()
                    blocks = data.get('results', [])
                    all_block_ids.extend([b['id'] for b in blocks])
                    
                    has_more = data.get('has_more', False)
                    next_cursor = data.get('next_cursor')
                    
                    if not has_more or not next_cursor:
                        break
                
                # Delete all blocks
                for block_id in all_block_ids:
                    requests.delete(f'{NOTION_API_URL}/blocks/{block_id}', headers=headers)
                
                print(f"   🗑️  Deleted {len(all_block_ids)} existing blocks")
        
        # Create new document if not found
        if not page_id:
            print("   📝 Creating new Master Update document...")
            page_data = {
                'parent': {'database_id': NOTION_DATABASE_ID},
                'icon': {
                    'type': 'emoji',
                    'emoji': '👷'
                },
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
            
            create_response = requests.post(
                f'{NOTION_API_URL}/pages',
                json=page_data,
                headers=headers
            )
            
            if create_response.status_code != 200:
                print(f"   ❌ Error creating Master Update: {create_response.status_code}")
                print(f"   Response: {create_response.text}")
                return False
            
            page_id = create_response.json()['id']
            print(f"   ✅ Created new Master Update document: {page_id}")
        
        # Add new blocks
        if master_blocks:
            blocks_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
            response = requests.patch(
                blocks_url,
                json={'children': master_blocks},
                headers=headers
            )
            
            if response.status_code == 200:
                print(f"   ✅ Successfully added {len(master_blocks)} blocks to Master Update")
                return True
            else:
                print(f"   ❌ Error adding blocks: {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        else:
            print("   ⚠️  No blocks to add")
            return True
            
    except Exception as e:
        print(f"   ❌ Exception managing Master Update: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_master_update_for_week():
    """
    Main function to generate Master Update for the nearest Friday.
    Fetches updates, deduplicates, and creates Master Update document.
    Returns True if successful, False otherwise.
    """
    try:
        print("\n" + "="*60)
        print("🔄 Generating Master Update...")
        print("="*60)
        
        # Calculate week ending date (nearest Friday)
        last_friday = get_last_friday_of_week()
        week_ending_date = last_friday.strftime('%Y-%m-%d')
        print(f"   Week ending on: {week_ending_date}")
        
        # Fetch all updates for this week
        print("\n📥 Fetching updates from All updates database...")
        updates = fetch_updates_for_week(week_ending_date)
        
        if not updates:
            print("   ⚠️  No updates found for this week")
            return True  # Not an error, just no updates
        
        # Deduplicate updates
        print("\n🔍 Deduplicating updates...")
        deduplicated = deduplicate_updates(updates)
        
        if not deduplicated:
            print("   ⚠️  No updates after deduplication")
            return True
        
        # Generate Master Update blocks
        print("\n📝 Generating Master Update content...")
        master_blocks = generate_master_update(deduplicated, week_ending_date)
        
        if not master_blocks:
            print("   ⚠️  No content blocks generated")
            return True
        
        # Create or replace Master Update document
        print("\n💾 Saving Master Update document...")
        success = find_or_replace_master_update(week_ending_date, master_blocks)
        
        if success:
            print("\n✅ Master Update generated successfully!")
        else:
            print("\n❌ Failed to generate Master Update")
        
        return success
        
    except Exception as e:
        print(f"\n❌ Error generating Master Update: {e}")
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
        
        # Get the update ID for deduplication
        update_id = project_update.get('id') or project_update.get('slugId')
        
        # Get updatedAt timestamp for deduplication
        updated_at = project_update.get('updatedAt')
        created_at = project_update.get('createdAt')
        
        # Check if this update was already processed
        if update_id:
            existing_page_id, stored_updated_at = find_existing_update_by_id(update_id)
            
            if existing_page_id:
                # Update exists, check if it was edited
                if updated_at and stored_updated_at:
                    # Compare timestamps (both stored as strings in rich_text)
                    try:
                        # First, try direct string comparison (fastest, exact match)
                        if updated_at == stored_updated_at:
                            # Exact match - duplicate webhook delivery
                            print(f"   ⏭️  Skipping duplicate webhook delivery (exact timestamp match)")
                            print(f"      Stored updatedAt: {stored_updated_at}")
                            print(f"      Webhook updatedAt: {updated_at}")
                            return True  # Return True to indicate successful handling (by skipping)
                        
                        # If strings don't match, parse and compare as datetime objects
                        # Normalize webhook timestamp
                        webhook_ts = updated_at.replace('Z', '+00:00') if updated_at.endswith('Z') else updated_at
                        webhook_time = datetime.fromisoformat(webhook_ts)
                        
                        # Normalize stored timestamp (may be from old date property or rich_text)
                        stored_ts = stored_updated_at.replace('Z', '+00:00') if stored_updated_at.endswith('Z') else stored_updated_at
                        stored_time = datetime.fromisoformat(stored_ts)
                        
                        # Compare timestamps
                        time_diff = (webhook_time - stored_time).total_seconds()
                        
                        if time_diff <= 0:
                            # Webhook timestamp is same or older, skip processing (duplicate delivery)
                            print(f"   ⏭️  Skipping duplicate webhook delivery (update already processed)")
                            print(f"      Stored updatedAt: {stored_updated_at}")
                            print(f"      Webhook updatedAt: {updated_at}")
                            print(f"      Time difference: {time_diff:.3f} seconds")
                            return True  # Return True to indicate successful handling (by skipping)
                        else:
                            # Update was edited (webhook timestamp is newer), we need to process it
                            print(f"   🔄 Update was edited, will update existing document")
                            print(f"      Stored updatedAt: {stored_updated_at}")
                            print(f"      Webhook updatedAt: {updated_at}")
                            print(f"      Time difference: {time_diff:.3f} seconds")
                    except Exception as e:
                        print(f"   ⚠️  Error comparing timestamps: {e}, processing anyway")
                        import traceback
                        print(traceback.format_exc())
                elif action == 'create':
                    # If we can't compare timestamps but action is 'create', it's likely a duplicate
                    print(f"   ⏭️  Skipping duplicate webhook delivery (update already exists, action=create)")
                    return True
                # If action is 'update', process it (it's an edit)
        
        # Get project information - could be nested or referenced by ID
        project = project_update.get('project')
        print(f"   Project data: {project}")
        if project:
            print(f"   Project object keys: {list(project.keys()) if isinstance(project, dict) else 'Not a dict'}")
            print(f"   Project object structure: {json.dumps(project, indent=2, ensure_ascii=False) if isinstance(project, dict) else project}")
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
        
        # Extract status information
        update_status = project_update.get('health')  # Update health status
        
        # Get project ID for fetching status
        project_id = None
        if project:
            project_id = project.get('id')
        elif project_update.get('projectId'):
            project_id = project_update.get('projectId')
        
        # Fetch project status from Linear API (not available in webhook)
        project_status = None
        if project_id:
            project_status = get_project_status(project_id)
        
        print(f"   Update status: {update_status or 'Not provided'}")
        print(f"   Project status: {project_status or 'Not provided'}")
        
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
        
        # Skip processing if update body is empty (unless it's an explicit update action)
        if not update_body or not update_body.strip():
            if action == 'create':
                print("⚠️  Skipping empty update (no content to process)")
                return True  # Return True to indicate successful handling (by skipping)
            else:
                print("⚠️  Warning: Update body is empty, but processing as edit")
        
        # Get team information
        team_names = []
        project_id = None
        
        # Try to get team information from webhook payload first
        if project:
            # Check for multiple teams
            teams = project.get('teams', {}).get('nodes', [])
            if teams:
                team_names = [team.get('name') for team in teams if team.get('name')]
            
            # If no teams found, check for single team
            if not team_names:
                team = project.get('team')
                if team:
                    if isinstance(team, dict):
                        team_name = team.get('name')
                        if team_name:
                            team_names = [team_name]
                    else:
                        # Team might be just an ID
                        team_id = team if isinstance(team, str) else None
                        if team_id:
                            team_name = get_team_name(team_id)
                            if team_name and team_name != "Unknown Team":
                                team_names = [team_name]
            
            # Get project ID for API fallback
            project_id = project.get('id')
        else:
            # Try to get team from projectUpdate directly
            team = project_update.get('team')
            if team:
                if isinstance(team, dict):
                    team_name = team.get('name')
                    if team_name:
                        team_names = [team_name]
                else:
                    team_id = team if isinstance(team, str) else None
                    if team_id:
                        team_name = get_team_name(team_id)
                        if team_name and team_name != "Unknown Team":
                            team_names = [team_name]
            
            # Get project ID for API fallback
            project_id = project_update.get('projectId') or project_update.get('project', {}).get('id')
        
        # If no team names found, try to fetch from Linear API using project ID
        if not team_names and project_id:
            print(f"   🔍 No team info in webhook payload, fetching from Linear API...")
            team_names = get_project_teams(project_id)
        
        # If still no teams found, try to get team ID and fetch single team
        if not team_names:
            team_id = None
            if project:
                team_id = project.get('teamId')
            elif project_update.get('teamId'):
                team_id = project_update.get('teamId')
            
            if team_id:
                print(f"   🔍 Fetching single team by ID: {team_id}")
                team_name = get_team_name(team_id)
                if team_name and team_name != "Unknown Team":
                    team_names = [team_name]
        
        # Format team name(s) for document title
        if team_names:
            # If multiple teams, join them with " & "
            team_name = " & ".join(team_names)
            print(f"   ✅ Team(s): {team_name}")
        else:
            # If no teams found, use project name as fallback
            team_name = project_name if project_name and project_name != "Unknown Project" else "Unknown Team"
            print(f"   ⚠️  Could not determine team name, using project name: {team_name}")
        
        # Calculate week ending date (last Friday)
        last_friday = get_last_friday_of_week()
        week_ending_date = last_friday.strftime('%Y-%m-%d')
        print(f"   Week ending on: {week_ending_date}")
        
        # Check if update already exists (for edit case)
        existing_page_id = None
        if update_id:
            existing_page_id, _ = find_existing_update_by_id(update_id)
        
        # Prepare headers for API calls
        headers = {
            'Authorization': f'Bearer {NOTION_API_KEY}',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28',
        }
        
        # Create or update document in All project updates database
        if existing_page_id:
            print(f"\n📄 Updating existing update document in All project updates database...")
            print(f"   Existing page ID: {existing_page_id}")
            print(f"   Project: {project_name}")
            print(f"   Update ID: {update_id}")
            
            # Update the updatedAt timestamp
            if updated_at:
                try:
                    # Store timestamp as rich_text to preserve exact format from Linear
                    update_props = {
                        'linear-updated-at': {
                            'rich_text': [
                                {
                                    'text': {
                                        'content': updated_at
                                    }
                                }
                            ]
                        }
                    }
                    update_response = requests.patch(
                        f'{NOTION_API_URL}/pages/{existing_page_id}',
                        json={'properties': update_props},
                        headers=headers
                    )
                    if update_response.status_code == 200:
                        print(f"   ✅ Updated linear-updated-at timestamp")
                    else:
                        print(f"   ⚠️  Failed to update timestamp: {update_response.status_code} - {update_response.text}")
                except Exception as e:
                    print(f"   ⚠️  Could not update timestamp: {e}")
                    import traceback
                    traceback.print_exc()
            
            page_id = existing_page_id
            
            # Delete existing content blocks to replace with new content
            print(f"   🗑️  Deleting existing content blocks...")
            blocks_url = f'{NOTION_API_URL}/blocks/{page_id}/children'
            all_block_ids = []
            next_cursor = None
            
            while True:
                params = {'page_size': 100}
                if next_cursor:
                    params['start_cursor'] = next_cursor
                
                get_response = requests.get(blocks_url, headers=headers, params=params)
                if get_response.status_code != 200:
                    break
                
                data = get_response.json()
                blocks = data.get('results', [])
                all_block_ids.extend([b['id'] for b in blocks])
                
                has_more = data.get('has_more', False)
                next_cursor = data.get('next_cursor')
                
                if not has_more or not next_cursor:
                    break
            
            # Delete all blocks
            for block_id in all_block_ids:
                requests.delete(f'{NOTION_API_URL}/blocks/{block_id}', headers=headers)
            
            print(f"   🗑️  Deleted {len(all_block_ids)} existing blocks")
        else:
            print(f"\n📄 Creating update document in All project updates database...")
            print(f"   Project: {project_name}")
            print(f"   Project ID: {project_id or 'Not provided'}")
            print(f"   Team: {team_name}")
            print(f"   Update ID: {update_id or 'Not provided'}")
            
            page_id = find_or_create_all_updates_document(
                project_name, 
                project_id or '', 
                team_name, 
                update_id or '', 
                week_ending_date,
                updated_at
            )
        
        if not page_id:
            print("❌ Failed to create update document in All updates database")
            return False
        
        print(f"✅ Update document created with ID: {page_id}")
        
        # Add the project update as blocks (same format as before)
        print(f"\n📝 Adding project update blocks...")
        print(f"   Project: {project_name}")
        if update_id:
            print(f"   Update ID: {update_id}")
        # Don't add marker for "All project updates" database - we use properties for tracking
        success = add_project_update_block(page_id, project_name, update_body, project_url, update_id, action, project_status, update_status, add_marker=False)
        
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
    import sys
    import traceback
    
    try:
        print("\n" + "="*60)
        print("📥 Webhook received at /webhook")
        print(f"   Method: {request.method}")
        print(f"   Headers: {dict(request.headers)}")
        print(f"   Content-Type: {request.content_type}")
        print(f"   Content-Length: {request.content_length}")
        print("="*60)
    except Exception as e:
        print(f"\n❌❌❌ ERROR IN WEBHOOK HANDLER START ❌❌❌")
        print(f"Error: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Internal server error'}), 500
    
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
        
        # Print the raw payload in a formatted way
        print("\n" + "="*60)
        print("📦 RAW WEBHOOK PAYLOAD:")
        print("="*60)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("="*60 + "\n")
        
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
        import sys
        import traceback
        
        error_msg = f"\n❌❌❌ ERROR HANDLING WEBHOOK ❌❌❌\n"
        error_msg += f"Error type: {type(e).__name__}\n"
        error_msg += f"Error message: {str(e)}\n"
        error_msg += "\nFull traceback:\n"
        
        # Print to stdout
        print(error_msg)
        traceback.print_exc()
        print("="*60)
        
        # Also print to stderr to ensure it's visible
        print(error_msg, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("="*60, file=sys.stderr)
        
        # Force flush
        sys.stdout.flush()
        sys.stderr.flush()
        
        # Don't expose internal errors to potential attackers
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        print("="*60 + "\n")
        import sys
        sys.stdout.flush()


@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint.
    """
    return jsonify({'status': 'ok'}), 200


@app.route('/generate-master-update', methods=['POST'])
def trigger_master_update():
    """
    Manually trigger Master Update generation.
    Useful for testing or manual runs.
    """
    try:
        print("\n" + "="*60)
        print("🔧 Manual Master Update trigger")
        print("="*60)
        success = generate_master_update_for_week()
        if success:
            return jsonify({'status': 'success', 'message': 'Master Update generated successfully'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to generate Master Update'}), 500
    except Exception as e:
        print(f"❌ Error in manual trigger: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/test-database/<database_id>', methods=['GET'])
def test_database(database_id):
    """
    Test if a database ID is accessible.
    Useful for debugging database access issues.
    """
    if not NOTION_API_KEY:
        return jsonify({'status': 'error', 'message': 'NOTION_API_KEY not set'}), 500
    
    # Format the ID
    formatted_id = format_notion_id(database_id)
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        response = requests.get(
            f'{NOTION_API_URL}/databases/{formatted_id}',
            headers=headers
        )
        
        if response.status_code == 200:
            db_info = response.json()
            db_title = db_info.get('title', [{}])[0].get('plain_text', 'Unknown')
            return jsonify({
                'status': 'success',
                'message': 'Database accessible',
                'database_id': formatted_id,
                'title': db_title,
                'raw_response': db_info
            }), 200
        else:
            error_data = response.json() if response.text else {}
            return jsonify({
                'status': 'error',
                'message': 'Database not accessible',
                'database_id': formatted_id,
                'status_code': response.status_code,
                'error': error_data.get('message', response.text)
            }), response.status_code
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'database_id': formatted_id
        }), 500


@app.route('/sample-timestamps', methods=['GET'])
def sample_timestamps():
    """
    Fetch sample timestamp values from the 'linear-updated-at' property
    in the All project updates database to understand Notion's format.
    """
    if not NOTION_API_KEY or not NOTION_ALL_UPDATES_DATABASE_ID:
        return jsonify({'error': 'Notion API key or database ID not configured'}), 500
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        query_url = f'{NOTION_API_URL}/databases/{NOTION_ALL_UPDATES_DATABASE_ID}/query'
        query_payload = {
            'page_size': 10,  # Get up to 10 samples
            'sorts': [
                {
                    'property': 'linear-updated-at',
                    'direction': 'descending'
                }
            ]
        }
        
        response = requests.post(query_url, json=query_payload, headers=headers)
        
        if response.status_code != 200:
            return jsonify({
                'error': f'Failed to query database: {response.status_code}',
                'response': response.text
            }), response.status_code
        
        results = response.json().get('results', [])
        samples = []
        
        for page in results:
            props = page.get('properties', {})
            updated_at_prop = props.get('linear-updated-at', {})
            prop_type = updated_at_prop.get('type')
            
            sample = {
                'page_id': page.get('id'),
                'property_type': prop_type,
                'raw_value': updated_at_prop,
            }
            
            if prop_type == 'date':
                date_obj = updated_at_prop.get('date', {})
                if date_obj:
                    sample['stored_value'] = date_obj.get('start')
                    sample['timezone'] = date_obj.get('time_zone')
            elif prop_type == 'rich_text':
                rich_text = updated_at_prop.get('rich_text', [])
                if rich_text:
                    sample['stored_value'] = rich_text[0].get('text', {}).get('content', '')
            
            samples.append(sample)
        
        return jsonify({
            'count': len(samples),
            'samples': samples
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({
            'error': f'Exception fetching samples: {str(e)}',
            'traceback': traceback.format_exc()
        }), 500


@app.route('/list-database-properties', methods=['GET'])
def list_database_properties():
    """
    List all properties of the All project updates database.
    Useful for debugging property name issues.
    """
    if not NOTION_API_KEY or not NOTION_ALL_UPDATES_DATABASE_ID:
        return jsonify({'status': 'error', 'message': 'NOTION_API_KEY and NOTION_ALL_UPDATES_DATABASE_ID must be set'}), 500
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    try:
        response = requests.get(
            f'{NOTION_API_URL}/databases/{NOTION_ALL_UPDATES_DATABASE_ID}',
            headers=headers
        )
        
        if response.status_code == 200:
            db_info = response.json()
            db_title = db_info.get('title', [{}])[0].get('plain_text', 'Unknown')
            properties = db_info.get('properties', {})
            
            # Format properties for display
            properties_list = []
            for prop_name, prop_data in properties.items():
                prop_type = prop_data.get('type', 'unknown')
                properties_list.append({
                    'name': prop_name,
                    'type': prop_type,
                    'details': prop_data
                })
            
            # Print to console as well
            print("\n" + "="*60)
            print(f"📋 Database: {db_title}")
            print(f"📋 Database ID: {NOTION_ALL_UPDATES_DATABASE_ID}")
            print("="*60)
            print("Properties:")
            for prop in properties_list:
                print(f"  - {prop['name']} ({prop['type']})")
            print("="*60 + "\n")
            
            return jsonify({
                'status': 'success',
                'database_title': db_title,
                'database_id': NOTION_ALL_UPDATES_DATABASE_ID,
                'properties': properties_list,
                'properties_count': len(properties_list)
            }), 200
        else:
            error_data = response.json() if response.text else {}
            return jsonify({
                'status': 'error',
                'message': 'Database not accessible',
                'status_code': response.status_code,
                'error': error_data.get('message', response.text)
            }), response.status_code
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


def is_friday_to_monday():
    """
    Check if current day is Friday, Saturday, Sunday, or Monday (in UTC).
    Returns True if it's one of these days, False otherwise.
    """
    # Get current UTC time
    now_utc = datetime.utcnow()
    # Get day of week (Monday=0, Sunday=6)
    day_of_week = now_utc.weekday()
    
    # Friday=4, Saturday=5, Sunday=6, Monday=0
    return day_of_week in [0, 4, 5, 6]


def run_master_update_with_retries(max_retries=5):
    """
    Run Master Update generation with retry logic.
    
    Args:
        max_retries: Maximum number of retry attempts
    
    Returns:
        True if successful, False otherwise
    """
    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n🔄 Attempt {attempt}/{max_retries} to generate Master Update...")
            success = generate_master_update_for_week()
            if success:
                print(f"✅ Master Update generated successfully on attempt {attempt}")
                return True
            else:
                if attempt < max_retries:
                    wait_time = attempt * 60  # Exponential backoff: 1min, 2min, 3min, etc.
                    print(f"⚠️  Attempt {attempt} failed, retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
        except Exception as e:
            print(f"❌ Error on attempt {attempt}: {e}")
            if attempt < max_retries:
                wait_time = attempt * 60
                print(f"   Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print(f"❌ All {max_retries} attempts failed")
                import traceback
                traceback.print_exc()
    
    return False


def cron_job_worker():
    """
    Background worker thread that runs the cron job scheduler.
    Checks every minute if it's time to run the Master Update generation.
    """
    if not SCHEDULE_AVAILABLE:
        print("⚠️  schedule library not available, cron jobs disabled")
        return
    
    if schedule is None:  # type: ignore
        print("⚠️  schedule module not loaded, cron jobs disabled")
        return
    
    def job():
        """Job to run - only execute if it's Friday-Monday"""
        if is_friday_to_monday():
            print("\n⏰ Cron job triggered (Friday-Monday)")
            run_master_update_with_retries()
        else:
            print(f"⏰ Cron job skipped (not Friday-Monday, current day: {datetime.utcnow().strftime('%A')})")
    
    # Schedule job to run every 2 hours
    schedule.every(2).hours.do(job)  # type: ignore
    
    print("🕐 Cron job scheduler started (runs every 2 hours, Friday-Monday only)")
    
    # Run the scheduler
    while True:
        schedule.run_pending()  # type: ignore
        time.sleep(60)  # Check every minute


def start_cron_job():
    """
    Start the cron job in a background thread.
    """
    if not SCHEDULE_AVAILABLE:
        print("⚠️  schedule library not available, install with: pip install schedule")
        return
    
    thread = threading.Thread(target=cron_job_worker, daemon=True)
    thread.start()
    print("✅ Cron job thread started")


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


def validate_notion_databases():
    """
    Validate that both Notion databases are accessible.
    Returns True if both are accessible, False otherwise.
    """
    if not NOTION_API_KEY:
        return False
    
    headers = {
        'Authorization': f'Bearer {NOTION_API_KEY}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    
    all_valid = True
    
    # Check weekly updates database
    if NOTION_DATABASE_ID:
        try:
            print(f"   Checking weekly updates database: {NOTION_DATABASE_ID}")
            response = requests.get(
                f'{NOTION_API_URL}/databases/{NOTION_DATABASE_ID}',
                headers=headers
            )
            if response.status_code == 200:
                db_info = response.json()
                db_title = db_info.get('title', [{}])[0].get('plain_text', 'Unknown')
                print(f"✅ Weekly updates database accessible: {db_title}")
            else:
                print(f"❌ Weekly updates database not accessible: {response.status_code}")
                print(f"   Response: {response.text}")
                all_valid = False
        except Exception as e:
            print(f"❌ Error checking weekly updates database: {e}")
            all_valid = False
    else:
        print("⚠️  NOTION_DATABASE_ID not set")
        all_valid = False
    
    # Check all updates database
    if NOTION_ALL_UPDATES_DATABASE_ID:
        try:
            print(f"   Checking all updates database: {NOTION_ALL_UPDATES_DATABASE_ID}")
            response = requests.get(
                f'{NOTION_API_URL}/databases/{NOTION_ALL_UPDATES_DATABASE_ID}',
                headers=headers
            )
            if response.status_code == 200:
                db_info = response.json()
                db_title = db_info.get('title', [{}])[0].get('plain_text', 'Unknown')
                print(f"✅ All updates database accessible: {db_title}")
            else:
                print(f"❌ All updates database not accessible: {response.status_code}")
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('message', response.text)
                print(f"   Error: {error_msg}")
                print(f"   💡 Troubleshooting steps:")
                print(f"      1. Open the database in Notion")
                print(f"      2. Click the '...' menu (top right) → 'Connections'")
                print(f"      3. Make sure your integration is connected")
                print(f"      4. If not connected, click 'Add connections' and select your integration")
                print(f"      5. Verify the database ID from the URL:")
                print(f"         - URL format: https://www.notion.so/XXXXXXXXXXXXX?v=...")
                print(f"         - Copy the XXXXXXXXXXXXX part (32 characters, no dashes)")
                print(f"         - Current ID in .env: {NOTION_ALL_UPDATES_DATABASE_ID}")
                all_valid = False
        except Exception as e:
            print(f"❌ Error checking all updates database: {e}")
            all_valid = False
    else:
        print("⚠️  NOTION_ALL_UPDATES_DATABASE_ID not set")
        all_valid = False
    
    return all_valid


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
    
    if not NOTION_ALL_UPDATES_DATABASE_ID:
        print("Error: NOTION_ALL_UPDATES_DATABASE_ID not set in .env file")
        return
    
    # Validate database access
    print("\n🔍 Validating Notion database access...")
    if not validate_notion_databases():
        print("\n❌ Database validation failed. Please check:")
        print("   1. Database IDs are correct in .env file")
        print("   2. Databases are shared with your Notion integration")
        print("   3. Notion integration has proper permissions")
        print("\n⚠️  Continuing anyway, but webhooks may fail...")
    else:
        print("✅ All databases validated successfully!\n")
    
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
        print(f"Manual Master Update trigger: http://localhost:{port}/generate-master-update (POST)")
        if not USE_NGROK:
            print("\n💡 To test with Linear webhooks locally, set USE_NGROK=true in .env")
            print("   and optionally set NGROK_AUTH_TOKEN for authenticated ngrok sessions\n")
    
    # Start cron job scheduler
    start_cron_job()
    
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
