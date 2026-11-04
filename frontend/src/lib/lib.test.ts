import { describe, expect, it } from "vitest";
import { formatDuration, formatMiles, toLocalInputValue } from "./format";
import { alphaAt, colorAt, LEVELS, valueAtHour } from "./risk";

describe("risk helpers", () => {
  it("colorAt returns the level colour at integer scores and blends in between", () => {
    expect(colorAt(0)).toEqual(LEVELS[0].rgb);
    expect(colorAt(4)).toEqual(LEVELS[4].rgb);
    const mid = colorAt(2.5);
    expect(mid[0]).toBeGreaterThan(Math.min(LEVELS[2].rgb[0], LEVELS[3].rgb[0]) - 1);
    expect(mid).not.toEqual(LEVELS[2].rgb);
  });

  it("clamps out-of-range scores", () => {
    expect(colorAt(-3)).toEqual(LEVELS[0].rgb);
    expect(colorAt(9)).toEqual(LEVELS[4].rgb);
  });

  it("alpha grows with risk but stays translucent", () => {
    expect(alphaAt(0)).toBeLessThan(alphaAt(2));
    expect(alphaAt(4)).toBeLessThanOrEqual(0.78);
  });

  it("valueAtHour interpolates and clamps", () => {
    const series = [0, 10, 20];
    expect(valueAtHour(series, 0.5)).toBe(5);
    expect(valueAtHour(series, 1.25)).toBe(12.5);
    expect(valueAtHour(series, 99)).toBe(20);
    expect(valueAtHour(series, -4)).toBe(0);
    expect(valueAtHour([], 3)).toBe(0);
  });
});

describe("format helpers", () => {
  it("formats durations", () => {
    expect(formatDuration(45 * 60)).toBe("45m");
    expect(formatDuration(6 * 3600 + 5 * 60)).toBe("6h 05m");
  });

  it("formats miles", () => {
    expect(formatMiles(12.34)).toBe("12.3");
    expect(formatMiles(1234.5)).toMatch(/1,?235/);
  });

  it("builds a datetime-local value", () => {
    expect(toLocalInputValue(new Date(2026, 10, 4, 9, 5))).toBe("2026-11-04T09:05");
  });
});
