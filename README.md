# Weather-Aware Truck Routing

A React + Django app that helps a truck driver pick the safest of three routes based on **weather along the way, load weight and travel time**.

Enter an origin, destination, departure time and load weight. The app:

1. gets **3 route options** from a routing API,
2. places **weather checkpoints every 10 / 25 / 50 miles** and works out the truck's **ETA at each one**,
3. reads the hourly forecast **at that ETA**, classifies each checkpoint (Low → No Travel) using the risk and load rules,
4. **recommends** a route (fewest Severe miles → fewest High miles → lowest average risk → shortest time) and explains why,
5. shows every route, checkpoint, risk level, ETA and summary on a map, plus a **weather heatmap over the trip corridor with a 0–48 hour forecast slider**.

| Brief | Where |
|---|---|
| Routing API, 3 options | `backend/weatherroute/providers/osrm.py` (OSRM + via-point fallback) |
| Sampling every 10/25/50 mi at ETA | `planner.py` (`choose_interval`, `_make_draft`) |
| Risk + load rules | `risk.py` (pure, exhaustively tested) |
| Recommendation | `recommend.py` |
| Map, checkpoints, ETAs, summaries | `frontend/src/components/MapView.tsx`, `RouteCards.tsx`, `CheckpointTable.tsx` |
| Heatmap + 0–48 h slider | `HeatLayer.tsx` (canvas layer), `ForecastSlider.tsx` |

## Data sources (no API keys needed)

| Purpose | Service | Notes |
|---|---|---|
| Routing | [OSRM](https://project-osrm.org/) public server | Car profile; durations are scaled for trucks (see below). Self-host and set `OSRM_BASE_URL` for production use. |
| Geocoding / autocomplete | [Photon](https://photon.komoot.io/), falling back to Nominatim | |
| Weather | [Open-Meteo](https://open-meteo.com/) hourly forecast | Free for non-commercial use. |
| Basemap | CARTO light tiles / OpenStreetMap | |

## Architecture

```
React (Vite, TS, Leaflet)  ── /api/plan ───────►  planner.plan_trip
   map · cards · slider    ── /api/heatmap ───►     ├─ geocode      (Photon → Nominatim)
                           ── /api/geocode ───►     ├─ 3 routes     (OSRM, via-point fallback)
                           ── /api/risk-rules ►     ├─ ETAs         (provider step durations × truck factor)
                                                    ├─ weather      (Open-Meteo, 1 batched, cached call)
                                                    ├─ risk.assess  (thresholds + load rules)
                                                    └─ recommend    (rank + explanation)
```

* **Two requests keep the UI fast.** `/api/plan` returns routes, checkpoints and the list of corridor points. The map renders immediately; the UI then calls `/api/heatmap` with those points to get 49 hourly values per point. The server stays stateless.
* **Weather is fetched in one batch** for every checkpoint of every route (chunked to 80 locations/request, run in parallel, cached per ~1 km cell for 30 minutes), so overlapping routes and repeat searches do not re-hit Open-Meteo.
* **The heatmap is a custom canvas layer**, not a heat plugin. It paints one soft, risk-coloured blob per corridor point from lowest to highest risk, so the worst nearby value wins. Plugins like `leaflet.heat` *add* overlapping intensities, which would make two Moderate neighbours look Severe. Blob size is in metres, so the field scales correctly with zoom. Values are interpolated between forecast hours, and the slider/play button drive the layer imperatively (`requestAnimationFrame`), so scrubbing never re-renders React.

## Risk logic and the decisions I made

The brief leaves some details open. These are the calls I made; each is in code, tested, and visible in the UI's "Risk rules" panel.

**Boundaries.** Ranges in the table touch (rain "0.10–0.25" and "0.25–0.50"). A value on a shared boundary belongs to the **higher** band (0.25 in/hr is High). No Travel follows the brief literally: wind `≥ 55`, rain `> 1.00`, snow `> 3.0` (so 1.00 in/hr rain is still Severe).

**Load rules** apply to wind only and never lower a level: `≥55 mph` → No Travel for any load; `45–54 mph` and `> 30,000 lb` → No Travel; `35–44 mph` and `> 40,000 lb` → Severe (so exactly 30,000 / 40,000 lb is *not* over the limit). The worst of wind, rain and snow sets the checkpoint level.

**Units and variables.** Open-Meteo is asked for mph and inches directly. Rain = `rain + showers` (in/hr); snow = `snowfall` (inches of new snow per hour). Wind is the sustained 10 m wind by default; set `WIND_METRIC=gust` to classify on gusts instead. Gusts are shown either way.

**Sampling interval.** The brief says "every 10 / 25 / 50 miles". I made that a choice: **Auto** (default) uses 10 mi under 150 mi, 25 mi under 600 mi and 50 mi beyond, or the user can force 10, 25 or 50. Checkpoints always include the origin and the exact destination.

**Time at each checkpoint.** ETA comes from the routing provider's per-step durations (so slow city stretches and fast highway stretches are respected), scaled by `TRUCK_DURATION_FACTOR` (default 1.10) because OSRM's public profile is a car. Weather is interpolated linearly between forecast hours at that ETA. If a trip outruns the forecast the last hour is used and the UI flags it.

**Miles per risk level.** "Severe miles" needs a definition. A checkpoint is responsible for the stretch around it, from the midpoint to the previous checkpoint to the midpoint to the next. Those stretches tile the route, so level miles always sum to total distance. Average risk is the distance-weighted mean of the level (Low = 0 … No Travel = 4).

**Recommendation.** Order from the brief: fewest Severe miles, fewest High miles, lowest average risk, shortest time. Two additions:
* **No Travel miles rank first.** A route you may not drive cannot beat one that is merely Severe. If every route crosses No Travel weather the app says so and suggests another departure time.
* **Near-ties.** Miles are only known to checkpoint resolution, and strict lexicographic order would let 0.4 mi of Severe beat a route two hours faster. Each criterion is bucketed (5 mi, 0.05 risk, 5 min); routes in the same bucket tie and the next criterion decides. That is how risk and travel time get "balanced".

The response includes the reasons (e.g. "Beats Route A on Severe miles: 0.0 mi vs 40 mi. Takes 12 min longer than Route C, the fastest route.").

**Heatmap semantics.** The heatmap shows the weather at one *clock time* across the whole corridor (what a forecast map shows), with the same thresholds and load rules. Checkpoint risk, by contrast, is the weather the truck actually meets at its own ETA. The slider track highlights the selected trip's duration so you can see which hours matter. The corridor is the three routes plus a lateral offset to either side, sampled on a grid capped at ~180 points.

## API

All responses are JSON; errors are `{"detail": "...", "code": "...", "fields"?: {...}}`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/plan` | `{origin, destination, departure, load_weight_lb, interval_miles?}`. `origin` / `destination` are text or `{lat, lon, label?}`. `departure` is ISO-8601. `interval_miles` is `"auto"`, 10, 25 or 50. Returns routes, checkpoints, risk summaries, recommendation, corridor points. |
| `POST` | `/api/heatmap` | `{points: [{lat, lon}], departure, load_weight_lb}`. Returns 49 hourly `risk / wind / rain / snow` values per point. |
| `GET` | `/api/geocode?q=` | Autocomplete suggestions (min 3 chars). |
| `GET` | `/api/risk-rules` | The thresholds and rules as data (the UI renders them from this). |
| `GET` | `/api/health` | Liveness. |

Status codes: `400` invalid input or departure outside the forecast window, `422` place or route not found, `502` an upstream API failed (after retries), `429` rate limit.

## Run locally

Requirements: Python 3.12+, Node 20+.

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py runserver            # http://127.0.0.1:8000

# frontend (second terminal)
cd frontend
npm install
npm run dev                           # http://localhost:5173 (proxies /api to :8000)
```

**Offline demo mode.** `PROVIDERS=fake python manage.py runserver` swaps in deterministic fake routing, geocoding (a handful of US cities) and a synthetic storm, so everything works with no network or API quotas. Useful for development and for a predictable demo; production uses `PROVIDERS=live` (the default).

Configuration is via environment variables; see [`.env.example`](.env.example).

## Tests

```bash
cd backend && python manage.py test     # 101 tests
cd frontend && npm test && npm run typecheck
```

Backend tests cover every threshold boundary and load rule, geometry helpers, ranking and explanations, the planner end to end (miles tile the route, ETAs, weather-at-ETA, forecast horizon, load weight changing the outcome), provider parsing/fallback/retry/caching against canned upstream responses, and the HTTP API. They run offline. CI (`.github/workflows/ci.yml`) runs both suites and the production build.

## Deploy

One Docker image serves the API and the built UI (WhiteNoise), so hosting is a single service.

* **Render:** *New → Blueprint* and select this repo. `render.yaml` is included; the secret key is generated for you. The health check is `/api/health`.
* **Anything that runs Docker:** `docker build -t truck-routing . && docker run -p 8000:8000 -e DJANGO_SECRET_KEY=... truck-routing`. Add your hostname to `DJANGO_ALLOWED_HOSTS`.

Free tiers sleep when idle, so the first request after a pause is slow.

## Known limitations and what I would do next

* **Car routing profile.** OSRM's public server routes cars. Real truck routing (height/weight restrictions, truck-legal roads) needs a truck profile such as OpenRouteService `driving-hgv`, GraphHopper or HERE. The routing provider is isolated behind `get_route_options`, so that is a one-class change.
* **Hours-of-service** (breaks, 11-hour driving limit) are not modelled; long trips use continuous driving time for ETAs.
* **Public APIs have fair-use limits.** Caching and batching keep usage low, but production needs a self-hosted OSRM and an Open-Meteo plan or equivalent.
* **Wind direction.** Crosswind and headwind are not modelled; the brief's rules use speed only.
* **Checkpoint resolution.** Risk and "miles at level" are only as fine as the sampling interval; a storm cell narrower than the spacing can be missed. The Auto interval trades this against API cost.
* **Times** are displayed in the browser's time zone, not the local time at each checkpoint.

## Project layout

```
backend/
  config/                 Django settings, urls, wsgi
  weatherroute/
    risk.py               thresholds + load rules (pure)
    geo.py                distances, resampling, slicing, simplification, corridor grid
    recommend.py          ranking + explanation (pure)
    planner.py            orchestration: routes → ETAs → weather → risk → recommendation
    providers/            osrm, geocode, openmeteo (+ fake for tests/demo)
    serializers.py views.py errors.py urls.py
    tests/
frontend/src/
  components/             MapView, HeatLayer, ForecastSlider, PlannerForm, RouteCards, CheckpointTable, ...
  lib/                    risk colours/interpolation, formatting
  api.ts types.ts App.tsx
docs/WALKTHROUGH.md       outline for the Loom recording
Dockerfile render.yaml .github/workflows/ci.yml
```
