/* eslint-disable @typescript-eslint/no-explicit-any */
import L from "leaflet";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { useMap } from "react-leaflet";
import { addHours, formatDateTime } from "../lib/format";
import { alphaAt, colorAt, levelInfo, valueAtHour } from "../lib/risk";
import type { HeatmapResponse } from "../types";

export interface HeatHandle {
  /** Fractional hours after departure (0..48). Redraws on the next animation frame; no React render. */
  setHour(hour: number): void;
}

interface Props {
  data: HeatmapResponse | null;
  visible: boolean;
}

const PANE = "riskHeat";
const METERS_PER_MILE = 1609.344;

/**
 * A canvas layer that paints one soft, risk-coloured blob per corridor point.
 *
 * Why not leaflet.heat: it *adds* overlapping intensities, which would make two neighbouring
 * Moderate points look Severe. Here blobs are painted lowest-risk first with normal alpha
 * compositing, so the worst nearby value always wins and colours stay faithful to the scale.
 * Blob radius is in metres (spacing between points), so the field scales correctly with zoom.
 * Time is continuous: values are interpolated between forecast hours, which is what makes the
 * slider and the play button look smooth.
 */
const RiskHeatLayer: any = (L.Layer as any).extend({
  initialize(this: any) {
    this._data = null;
    this._hour = 0;
    this._visible = true;
    this._raf = 0;
  },

  onAdd(this: any, map: L.Map) {
    this._canvas = L.DomUtil.create("canvas", "risk-heat-canvas leaflet-zoom-animated") as HTMLCanvasElement;
    map.getPane(PANE)!.appendChild(this._canvas);
    this._reset();
    return this;
  },

  onRemove(this: any, map: L.Map) {
    cancelAnimationFrame(this._raf);
    this._raf = 0;
    L.DomUtil.remove(this._canvas);
    if (this._popup) map.closePopup(this._popup);
  },

  getEvents(this: any) {
    const events: Record<string, unknown> = { moveend: this._reset, resize: this._reset, click: this._onClick };
    if (this._map._zoomAnimated) events.zoomanim = this._animateZoom;
    return events;
  },

  setData(this: any, data: HeatmapResponse | null) {
    this._data = data;
    this._schedule();
  },

  setHour(this: any, hour: number) {
    this._hour = hour;
    this._schedule();
  },

  setVisible(this: any, visible: boolean) {
    this._visible = visible;
    this._schedule();
  },

  _animateZoom(this: any, e: any) {
    const scale = this._map.getZoomScale(e.zoom);
    const offset = this._map._latLngBoundsToNewLayerBounds(this._map.getBounds(), e.zoom, e.center).min;
    L.DomUtil.setTransform(this._canvas, offset, scale);
  },

  _reset(this: any) {
    if (!this._map) return;
    const size = this._map.getSize();
    const dpr = window.devicePixelRatio || 1;
    L.DomUtil.setPosition(this._canvas, this._map.containerPointToLayerPoint([0, 0]));
    this._canvas.width = Math.round(size.x * dpr);
    this._canvas.height = Math.round(size.y * dpr);
    this._canvas.style.width = `${size.x}px`;
    this._canvas.style.height = `${size.y}px`;
    this._draw();
  },

  _schedule(this: any) {
    if (this._raf || !this._map) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      this._draw();
    });
  },

  _radiusPx(this: any, lat: number): number {
    const metersPerPixel = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, this._map.getZoom());
    return Math.max(10, (this._data.spacing_miles * METERS_PER_MILE * 0.95) / metersPerPixel);
  },

  _draw(this: any) {
    if (!this._map || !this._canvas) return;
    const ctx = this._canvas.getContext("2d") as CanvasRenderingContext2D;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
    if (!this._visible || !this._data) return;

    const dpr = window.devicePixelRatio || 1;
    ctx.scale(dpr, dpr);
    const size = this._map.getSize();
    const hour: number = this._hour;

    const items = (this._data as HeatmapResponse).points.map((p) => ({ p, v: valueAtHour(p.risk, hour) }));
    items.sort((a, b) => a.v - b.v);

    for (const { p, v } of items) {
      const pt = this._map.latLngToContainerPoint([p.lat, p.lon]);
      const r = this._radiusPx(p.lat);
      if (pt.x < -r || pt.y < -r || pt.x > size.x + r || pt.y > size.y + r) continue;
      const [R, G, B] = colorAt(v);
      const a = alphaAt(v);
      const g = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, r);
      g.addColorStop(0, `rgba(${R},${G},${B},${a})`);
      g.addColorStop(0.55, `rgba(${R},${G},${B},${(a * 0.55).toFixed(3)})`);
      g.addColorStop(1, `rgba(${R},${G},${B},0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  },

  /** Click anywhere on the corridor to read the forecast for the nearest point at the current hour. */
  _onClick(this: any, e: L.LeafletMouseEvent) {
    if (!this._visible || !this._data) return;
    const click = this._map.latLngToContainerPoint(e.latlng);
    let best: HeatmapResponse["points"][number] | null = null;
    let bestDist = Infinity;
    for (const p of (this._data as HeatmapResponse).points) {
      const pt = this._map.latLngToContainerPoint([p.lat, p.lon]);
      const d = Math.hypot(pt.x - click.x, pt.y - click.y);
      if (d < bestDist && d <= this._radiusPx(p.lat)) {
        best = p;
        bestDist = d;
      }
    }
    if (!best) return;
    const h = Math.max(0, Math.min(best.risk.length - 1, Math.round(this._hour)));
    const info = levelInfo(best.risk[h]);
    const when = formatDateTime(addHours((this._data as HeatmapResponse).start, h));
    const html =
      `<div class="heat-popup"><strong style="color:${info.color}">${info.label}</strong>` +
      `<span class="muted"> · ${when}</span><br/>Wind ${best.wind[h]} mph · Rain ${best.rain[h].toFixed(2)} in/hr · ` +
      `Snow ${best.snow[h].toFixed(1)} in/hr</div>`;
    this._popup = L.popup({ offset: [0, -2] }).setLatLng([best.lat, best.lon]).setContent(html).openOn(this._map);
  },
});

export const HeatLayer = forwardRef<HeatHandle, Props>(function HeatLayer({ data, visible }, ref) {
  const map = useMap();
  const layerRef = useRef<any>(null);

  useEffect(() => {
    if (!map.getPane(PANE)) {
      const pane = map.createPane(PANE);
      pane.style.zIndex = "350"; // above tiles (200), below routes (410+)
      pane.style.pointerEvents = "none";
    }
    const layer = new RiskHeatLayer();
    layer.addTo(map);
    layerRef.current = layer;
    return () => {
      layer.remove();
      layerRef.current = null;
    };
  }, [map]);

  useEffect(() => layerRef.current?.setData(data), [data]);
  useEffect(() => layerRef.current?.setVisible(visible), [visible]);
  useImperativeHandle(ref, () => ({ setHour: (h: number) => layerRef.current?.setHour(h) }), []);

  return null;
});
