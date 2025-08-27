# Teamsy

Teamsy is a simple app that records Microsoft Teams availability for every user in a tenant. The
backend polls the Microsoft Graph hourly and stores each user's presence in a PostgreSQL database.
Users sign in via Azure AD (OIDC) to view the historical data through a small frontend.


### Environment variables

- `TENANT_ID`
- `CLIENT_ID`
- `CLIENT_SECRET`

### API permissions required
- Directory.Read.All
- GroupMember.Read.All
- Presence.Read.All
- User.Read

For both Delegated and Application
