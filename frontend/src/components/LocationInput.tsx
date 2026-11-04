import { useEffect, useState } from "react";
import { searchPlaces } from "../api";
import type { LocationRef } from "../types";

export interface LocationValue {
  text: string;
  /** Set when the user chose a suggestion, so the backend can skip geocoding. */
  picked: LocationRef | null;
}

interface Props {
  id: string;
  label: string;
  value: LocationValue;
  onChange: (value: LocationValue) => void;
  placeholder?: string;
  error?: string;
}

/** Text input with debounced, keyboard-navigable suggestions (ARIA combobox). */
export function LocationInput({ id, label, value, onChange, placeholder, error }: Props) {
  const [options, setOptions] = useState<LocationRef[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const listId = `${id}-listbox`;

  useEffect(() => {
    const query = value.text.trim();
    if (!open || value.picked || query.length < 3) {
      setOptions([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await searchPlaces(query, controller.signal);
        setOptions(res.results);
        setActive(-1);
      } catch (err) {
        if ((err as Error).name !== "AbortError") setOptions([]);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value.text, value.picked, open]);

  const pick = (option: LocationRef) => {
    onChange({ text: option.label, picked: option });
    setOpen(false);
    setOptions([]);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!options.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % options.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i <= 0 ? options.length - 1 : i - 1));
    } else if (e.key === "Enter" && active >= 0 && open) {
      e.preventDefault();
      pick(options[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const expanded = open && options.length > 0;

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="combo">
        <input
          id={id}
          type="text"
          autoComplete="off"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${id}-opt-${active}` : undefined}
          aria-invalid={error ? true : undefined}
          placeholder={placeholder}
          value={value.text}
          onChange={(e) => {
            onChange({ text: e.target.value, picked: null });
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        {loading && <span className="combo-spinner spinner" aria-hidden="true" />}
        {expanded && (
          <ul id={listId} role="listbox" className="combo-list">
            {options.map((o, i) => (
              <li
                key={`${o.lat},${o.lon},${i}`}
                id={`${id}-opt-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "active" : undefined}
                // mousedown (not click) so the input's blur doesn't close the list first
                onMouseDown={(e) => {
                  e.preventDefault();
                  pick(o);
                }}
              >
                {o.label}
              </li>
            ))}
          </ul>
        )}
      </div>
      {error && <p className="field-error">{error}</p>}
    </div>
  );
}
