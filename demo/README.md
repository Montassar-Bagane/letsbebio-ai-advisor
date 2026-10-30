# Standalone demo

A single HTML page that talks to the API directly — no WordPress needed.
Useful for showing the system on any laptop.

```bash
make demo                     # or: python3 -m http.server 8080
```

Then open <http://localhost:8080>.

The API must be running, and `http://localhost:8080` must be listed in
`CORS_ORIGINS` in `service/.env`. The WordPress plugin does not need this,
because there the browser talks to WordPress rather than to the API.
