# Loom walkthrough outline (target 8 minutes, limit 5–10)

Record with the hosted app open. Use a trip where the routes visibly differ in weather. In live mode that depends on the real forecast, so do a dry run first and pick a pair that shows a difference (a long cross-country trip in winter usually does). If you need a guaranteed storm, run locally with `PROVIDERS=fake` (try Chicago → Denver); say so out loud if you do.

| Time | Section | What to show / say |
|---|---|---|
| 0:00 | **Intro** (30 s) | What the app does in one sentence: picks the safest of 3 routes from weather at the time the truck actually gets there, load weight and travel time. Name the stack: React + Leaflet, Django + DRF, OSRM / Open-Meteo. |
| 0:30 | **Plan a trip** (1 min) | Type an origin (show autocomplete, keyboard nav), destination, departure, load weight. Mention the checkpoint spacing control: Auto vs 10/25/50 mi. Submit. |
| 1:30 | **Results** (1.5 min) | Recommendation banner and *why* (reasons list). Route cards: duration, miles at each level, average risk. Click between routes: map highlights, checkpoint table updates. Hover checkpoints (ETA, wind/rain/snow, reason). Click a table row to fly to that checkpoint. |
| 3:00 | **Heatmap + slider** (1.5 min) | Drag the 0–48 h slider; hit play. Point out: teal part of the track is the selected trip's duration; "Worst: …" chip; click the map for a point forecast. Change load weight (e.g. 25,000 → 42,000 lb) and re-run to show load rules changing the outcome. |
| 4:30 | **How the risk logic works** (1.5 min) | Open `risk.py`: thresholds as data, boundary convention, the three load rules, `assess()`. Show the in-app "Risk rules" panel (served from `/api/risk-rules`). Open `recommend.py`: order of preference, why No Travel miles rank first, the tie bands. |
| 6:00 | **Planner and data flow** (1 min) | `planner.plan_trip`: routes → ETAs from step durations → one batched weather call → per-checkpoint risk → miles attribution (checkpoint spans tile the route). Mention caching and chunked parallel fetches in `openmeteo.py`. |
| 7:00 | **Tests and quality** (45 s) | `python manage.py test` (101 tests, offline). Boundary tests, planner scenarios, provider parsing with canned responses. CI workflow. |
| 7:45 | **Trade-offs and next steps** (45 s) | Car profile → truck-routing API; HOS not modelled; public API limits → self-host OSRM; heatmap shows clock-time weather while checkpoints use ETA weather. Close. |

## Tips

* Zoom the browser to ~110% so text is readable in the recording.
* Show the error path once (e.g. an unknown place) to demonstrate clear messages.
* If the hosted app is on a free tier it may be asleep: open it a minute before recording.
