import requests
import datetime
from google.cloud import secretmanager
from google.cloud import storage
import os
import json
from flask import jsonify

# Initialize the Cloud Storage client
storage_client = storage.Client()
bucket_name = os.getenv('GCS_BUCKET_NAME')
bucket = storage_client.bucket(bucket_name)

# Configuration
INVENTORY_THRESHOLD = 2
REMINDER_DAYS = 7  # Number of days before sending a reminder

def load_inventory_alerts():
    try:
        blob = bucket.blob("inventory_alerts.json")
        if blob.exists():
            data = blob.download_as_string()
            return json.loads(data)
        return {
            "alerted_items": {},  # Format: {variant_id: {"last_alert": timestamp, "inventory": count}}
            "pending_reminders": {}  # Format: {variant_id: next_reminder_date}
        }
    except Exception as e:
        print(f"Error loading inventory alerts: {e}")
        return {"alerted_items": {}, "pending_reminders": {}}

def save_inventory_alerts(alert_data):
    try:
        blob = bucket.blob("inventory_alerts.json")
        blob.upload_from_string(json.dumps(alert_data))
    except Exception as e:
        print(f"Error saving inventory alerts: {e}")

def check_inventory():
    headers = {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN
    }
    url = f'https://{SHOPIFY_STORE_NAME}.myshopify.com/admin/api/2023-10/products.json'
    
    low_inventory_items = []
    alert_data = load_inventory_alerts()
    current_time = datetime.datetime.now().isoformat()
    
    try:
        response = requests.get(url, headers=headers)
        products = response.json().get("products", [])
        
        for product in products:
            for variant in product.get("variants", []):
                variant_id = str(variant["id"])
                inventory = variant.get("inventory_quantity", 0)
                
                # Check if inventory is low
                if inventory <= INVENTORY_THRESHOLD:
                    # Check if we haven't alerted for this item or if it was previously replenished
                    if (variant_id not in alert_data["alerted_items"] or 
                        alert_data["alerted_items"][variant_id]["inventory"] < inventory):
                        low_inventory_items.append({
                            "product_title": product["title"],
                            "variant_title": variant["title"],
                            "inventory": inventory,
                            "variant_id": variant_id
                        })
                        # Update alert tracking
                        alert_data["alerted_items"][variant_id] = {
                            "last_alert": current_time,
                            "inventory": inventory
                        }
                        # Set reminder
                        reminder_date = (datetime.datetime.now() + 
                                      datetime.timedelta(days=REMINDER_DAYS)).isoformat()
                        alert_data["pending_reminders"][variant_id] = reminder_date
                
                # Check if inventory was replenished
                elif variant_id in alert_data["alerted_items"]:
                    # Remove from tracking if replenished
                    del alert_data["alerted_items"][variant_id]
                    if variant_id in alert_data["pending_reminders"]:
                        del alert_data["pending_reminders"][variant_id]
        
        # Send alerts if needed
        if low_inventory_items:
            send_inventory_alert(low_inventory_items)
        
        # Check for pending reminders
        check_reminders(alert_data)
        
        # Save updated alert data
        save_inventory_alerts(alert_data)
        
    except Exception as e:
        print(f"Error checking inventory: {e}")

def send_inventory_alert(items, is_reminder=False):
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    sender_email = os.getenv('ALERT_SENDER_EMAIL')
    recipient_emails = [email.strip() for email in os.getenv('ALERT_RECIPIENT_EMAIL').split(',')]

    subject = "Low Inventory Alert" if not is_reminder else "Low Inventory Reminder"
    body_lines = ["The following items have low inventory:\n"]
    
    for item in items:
        body_lines.append(
            f"- {item['product_title']} ({item['variant_title']}): "
            f"{item['inventory']} items remaining\n"
        )

    body = "".join(body_lines)
    
    message = Mail(
        from_email=sender_email,
        to_emails=recipient_emails,
        subject=subject,
        plain_text_content=body
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print("Inventory alert email sent successfully.")
    except Exception as e:
        print(f"Failed to send inventory alert email: {e}")

def check_reminders(alert_data):
    current_time = datetime.datetime.now()
    reminder_items = []
    
    for variant_id, reminder_date in list(alert_data["pending_reminders"].items()):
        if current_time >= datetime.datetime.fromisoformat(reminder_date):
            if variant_id in alert_data["alerted_items"]:
                item_data = alert_data["alerted_items"][variant_id]
                # Get product details again to include in reminder
                # (You'll need to implement this part to fetch current product info)
                reminder_items.append({
                    "variant_id": variant_id,
                    # Add other product details here
                })
            # Update or remove reminder
            del alert_data["pending_reminders"][variant_id]
    
    if reminder_items:
        send_inventory_alert(reminder_items, is_reminder=True)

def main(request):
    print("Starting inventory check...")
    check_inventory()
    return jsonify({"status": "Inventory check complete"}), 200

if __name__ == "__main__":
    main(None) 