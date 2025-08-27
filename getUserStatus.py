import requests
from dotenv import load_dotenv
from os import getenv

load_dotenv()

r = requests.post(f"https://login.microsoftonline.com/{getenv('TENANT_ID')}/oauth2/v2.0/token", headers={
    "Content-Type": "application/x-www-form-urlencoded"
}, data={
    "grant_type": "client_credentials",
    "client_id": getenv("CLIENT_ID"),
    "client_secret": getenv("CLIENT_SECRET"),
    "scope": "https://graph.microsoft.com/.default"
})

token = r.json()["access_token"]

rGroupMembers = requests.get(f"https://graph.microsoft.com/v1.0/groups/{getenv('GROUP_ID')}/members", headers={
    "Authorization": f"Bearer {token}"
})

members = []
for member in rGroupMembers.json()["value"]:
    members.append(member["id"])

rPresence = requests.post(f"https://graph.microsoft.com/v1.0/communications/getPresencesByUserId", headers={
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}, json={
    "ids": members
})

print(rPresence.json())