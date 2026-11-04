import { useState } from "react";
import { nextHour, toLocalInputValue } from "../lib/format";
import type { IntervalChoice, PlanRequest } from "../types";
import { LocationInput, type LocationValue } from "./LocationInput";

interface Props {
  busy: boolean;
  onSubmit: (request: PlanRequest) => void;
}

const INTERVALS: { value: IntervalChoice; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: 10, label: "10 mi" },
  { value: 25, label: "25 mi" },
  { value: 50, label: "50 mi" },
];

const EMPTY: LocationValue = { text: "", picked: null };

export function PlannerForm({ busy, onSubmit }: Props) {
  const [origin, setOrigin] = useState<LocationValue>(EMPTY);
  const [destination, setDestination] = useState<LocationValue>(EMPTY);
  const [departure, setDeparture] = useState(() => toLocalInputValue(nextHour()));
  const [load, setLoad] = useState("35000");
  const [interval, setInterval] = useState<IntervalChoice>("auto");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const swap = () => {
    setOrigin(destination);
    setDestination(origin);
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const next: Record<string, string> = {};
    if (!origin.text.trim()) next.origin = "Enter a starting point.";
    if (!destination.text.trim()) next.destination = "Enter a destination.";
    const weight = Number(load);
    if (load.trim() === "" || !Number.isFinite(weight) || weight < 0 || weight > 100000) {
      next.load = "Enter a weight between 0 and 100,000 lb.";
    }
    const when = new Date(departure);
    if (!departure || Number.isNaN(when.getTime())) next.departure = "Pick a departure date and time.";
    setErrors(next);
    if (Object.keys(next).length) return;

    onSubmit({
      origin: origin.picked ?? origin.text.trim(),
      destination: destination.picked ?? destination.text.trim(),
      departure: when.toISOString(),
      load_weight_lb: weight,
      interval_miles: interval,
    });
  };

  const now = new Date();
  const max = new Date(now.getTime() + 6 * 86400_000);

  return (
    <form className="card planner" onSubmit={submit} noValidate>
      <h2>Plan a trip</h2>
      <LocationInput
        id="origin"
        label="Origin"
        placeholder="e.g. Chicago, IL"
        value={origin}
        onChange={setOrigin}
        error={errors.origin}
      />
      <div className="swap-row">
        <button type="button" className="ghost icon-btn" onClick={swap} aria-label="Swap origin and destination" title="Swap">
          ⇅
        </button>
      </div>
      <LocationInput
        id="destination"
        label="Destination"
        placeholder="e.g. Denver, CO"
        value={destination}
        onChange={setDestination}
        error={errors.destination}
      />

      <div className="row two">
        <div className="field">
          <label htmlFor="departure">Departure</label>
          <input
            id="departure"
            type="datetime-local"
            value={departure}
            min={toLocalInputValue(new Date(now.getTime() - 3600_000))}
            max={toLocalInputValue(max)}
            onChange={(e) => setDeparture(e.target.value)}
            aria-invalid={errors.departure ? true : undefined}
          />
          {errors.departure && <p className="field-error">{errors.departure}</p>}
        </div>
        <div className="field">
          <label htmlFor="load">Load weight (lb)</label>
          <input
            id="load"
            type="number"
            inputMode="numeric"
            min={0}
            max={100000}
            step={500}
            value={load}
            onChange={(e) => setLoad(e.target.value)}
            aria-invalid={errors.load ? true : undefined}
          />
          {errors.load && <p className="field-error">{errors.load}</p>}
        </div>
      </div>

      <fieldset className="field segmented">
        <legend>Weather checkpoint spacing</legend>
        <div className="seg-group">
          {INTERVALS.map((opt) => (
            <label key={String(opt.value)} className={interval === opt.value ? "on" : undefined}>
              <input
                type="radio"
                name="interval"
                checked={interval === opt.value}
                onChange={() => setInterval(opt.value)}
              />
              {opt.label}
            </label>
          ))}
        </div>
        <p className="hint">Auto uses 10 mi under 150 mi, 25 mi under 600 mi, otherwise 50 mi.</p>
      </fieldset>

      <button type="submit" className="primary" disabled={busy}>
        {busy ? "Analyzing routes…" : "Find safest route"}
      </button>
    </form>
  );
}
